"""
logging.py — structured logging + request-ID correlation (audit #12).

- setup_logging() installs a dictConfig: one stdout handler on the root logger,
  level from settings.log_level, formatter chosen by settings.log_json
  (JSON in production, pretty locally). All existing `logging.getLogger(__name__)`
  callers propagate to it — no call-site changes needed.
- RequestIdMiddleware mints (or honours an inbound) X-Request-ID, binds it to a
  contextvar, and echoes it on the response. RequestIdFilter injects that id into
  every LogRecord, so all lines emitted during a request share one id.

Pure-ASGI middleware (not BaseHTTPMiddleware) so it doesn't buffer the SSE
streaming endpoints (ai/query/stream, draft/stream, pleading-urdu/stream).
"""
from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import settings

# Bound per-request by RequestIdMiddleware; "-" outside any request (startup, schedulers).
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every record so formatters can render it."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    """One-line JSON per record — ready for Datadog/ELK ingestion."""
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":         datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level":      record.levelname,
            "logger":     record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message":    record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _use_json() -> bool:
    if settings.log_json is not None:
        return settings.log_json
    return settings.app_env == "production"


def setup_logging() -> None:
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "app.core.logging.RequestIdFilter"},
        },
        "formatters": {
            "json": {"()": "app.core.logging.JsonFormatter"},
            "pretty": {
                "format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
                "datefmt": "%H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json" if _use_json() else "pretty",
                "filters": ["request_id"],
            },
        },
        "root": {"level": settings.log_level.upper(), "handlers": ["default"]},
        # Route uvicorn through the same handler so access/error lines are
        # structured and carry the request id too.
        "loggers": {
            name: {"level": "INFO", "handlers": ["default"], "propagate": False}
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
        },
    })


class RequestIdMiddleware:
    """Pure-ASGI: bind a request id for the lifetime of each HTTP request and
    echo it on the response as X-Request-ID."""
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        rid = incoming.decode("latin-1")[:64] if incoming else uuid4().hex
        token = request_id_ctx.set(rid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", rid.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)

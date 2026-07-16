"""Tracing — a callback handler that records what the agent actually did.

Motivation: the chat graph runs 12 nodes, two retry loops, four LLM providers
with failover, a semantic cache and (now) five callable tools. When an answer
comes out wrong, "which provider served it, did the cache hit, which tool ran,
with what arguments, and how long did each take" was previously unanswerable.
This makes it answerable.

Emits one structured log line per event, and accumulates an in-memory trace that
can be attached to a response for debugging (see `get_trace`).

Deliberately NOT LangSmith: this keeps traces on your own infrastructure (client
legal data must not leave it) and adds no external dependency.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger("attorney.trace")

# The trace for the request currently being served. A ContextVar (not a global)
# so concurrent requests cannot interleave their spans.
_current_trace: ContextVar[list[dict] | None] = ContextVar("current_trace", default=None)

# Cap so a runaway loop cannot grow the trace without bound.
_MAX_SPANS = 200


def _now() -> float:
    return time.perf_counter()


def _truncate(value: Any, limit: int = 500) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


class TraceHandler(AsyncCallbackHandler):
    """Records tool calls, LLM calls and chain (node) transitions with timings."""

    def __init__(self, session_id: str = "", request_id: str = "") -> None:
        self.session_id = session_id
        self.request_id = request_id or str(uuid.uuid4())
        self.spans: list[dict] = []
        self._started: dict[UUID, tuple[str, str, float]] = {}

    # ── internals ────────────────────────────────────────────────────────────

    def _open(self, run_id: UUID, kind: str, name: str) -> None:
        self._started[run_id] = (kind, name, _now())

    def _close(self, run_id: UUID, status: str, **fields: Any) -> dict | None:
        started = self._started.pop(run_id, None)
        if started is None:
            return None
        kind, name, t0 = started
        span = {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "kind":       kind,
            "name":       name,
            "status":     status,
            "ms":         round((_now() - t0) * 1000, 1),
            **fields,
        }
        if len(self.spans) < _MAX_SPANS:
            self.spans.append(span)
        return span

    # ── tools ────────────────────────────────────────────────────────────────

    async def on_tool_start(self, serialized: dict, input_str: str, *,
                            run_id: UUID, inputs: dict | None = None, **kw: Any) -> None:
        name = (serialized or {}).get("name", "unknown_tool")
        self._open(run_id, "tool", name)
        logger.info(
            "tool.start name=%s args=%s request_id=%s",
            name, _truncate(inputs if inputs is not None else input_str, 300), self.request_id,
        )

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, "ok", output=_truncate(output, 300))
        if span:
            logger.info(
                "tool.end   name=%s ms=%s output=%s request_id=%s",
                span["name"], span["ms"], span["output"], self.request_id,
            )

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, "error", error=_truncate(error, 300))
        if span:
            logger.warning(
                "tool.error name=%s ms=%s error=%s request_id=%s",
                span["name"], span["ms"], span["error"], self.request_id,
            )

    # ── LLM ──────────────────────────────────────────────────────────────────

    async def on_llm_start(self, serialized: dict, prompts: list[str], *,
                           run_id: UUID, **kw: Any) -> None:
        self._open(run_id, "llm", _model_name(serialized, kw))

    async def on_chat_model_start(self, serialized: dict, messages: list, *,
                                  run_id: UUID, **kw: Any) -> None:
        self._open(run_id, "llm", _model_name(serialized, kw))

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kw: Any) -> None:
        usage = _token_usage(response)
        span = self._close(run_id, "ok", **usage)
        if span:
            logger.info(
                "llm.end    model=%s ms=%s tokens_in=%s tokens_out=%s request_id=%s",
                span["name"], span["ms"], span.get("tokens_in", "?"),
                span.get("tokens_out", "?"), self.request_id,
            )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, "error", error=_truncate(error, 200))
        if span:
            # This is the line that tells you a provider failed over.
            logger.warning(
                "llm.error  model=%s ms=%s error=%s request_id=%s",
                span["name"], span["ms"], span["error"], self.request_id,
            )

    # ── graph nodes ──────────────────────────────────────────────────────────

    async def on_chain_start(self, serialized: dict, inputs: Any, *,
                             run_id: UUID, **kw: Any) -> None:
        name = (kw.get("name") or (serialized or {}).get("name") or "")
        # LangGraph emits a chain event per node; ignore the noisy internal ones.
        if not name.endswith("_node"):
            return
        self._open(run_id, "node", name)

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, "ok")
        if span:
            logger.info("node.end   name=%s ms=%s request_id=%s",
                        span["name"], span["ms"], self.request_id)

    async def on_chain_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        span = self._close(run_id, "error", error=_truncate(error, 200))
        if span:
            logger.warning("node.error name=%s ms=%s error=%s request_id=%s",
                           span["name"], span["ms"], span["error"], self.request_id)

    # ── summary ──────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Compact, log-friendly rollup of the whole run."""
        tools = [s for s in self.spans if s["kind"] == "tool"]
        llms  = [s for s in self.spans if s["kind"] == "llm"]
        return {
            "request_id":  self.request_id,
            "session_id":  self.session_id,
            "total_ms":    round(sum(s["ms"] for s in self.spans if s["kind"] == "node"), 1),
            "llm_calls":   len(llms),
            "llm_ms":      round(sum(s["ms"] for s in llms), 1),
            "tokens_in":   sum(s.get("tokens_in", 0) for s in llms),
            "tokens_out":  sum(s.get("tokens_out", 0) for s in llms),
            "tool_calls":  [s["name"] for s in tools],
            "errors":      [f"{s['kind']}:{s['name']}" for s in self.spans if s["status"] == "error"],
        }


def _model_name(serialized: dict, kw: dict) -> str:
    meta = kw.get("metadata") or {}
    inv = kw.get("invocation_params") or {}
    return (
        inv.get("model")
        or inv.get("model_name")
        or meta.get("ls_model_name")
        or (serialized or {}).get("name")
        or "llm"
    )


def _token_usage(response: Any) -> dict:
    """Best-effort token extraction — providers disagree on where they put it."""
    try:
        output = getattr(response, "llm_output", None) or {}
        usage = output.get("token_usage") or output.get("usage") or {}
        if not usage:
            gens = getattr(response, "generations", None) or []
            if gens and gens[0]:
                msg = getattr(gens[0][0], "message", None)
                usage = getattr(msg, "usage_metadata", None) or {}
        if not usage:
            return {}
        return {
            "tokens_in":  usage.get("prompt_tokens")     or usage.get("input_tokens")  or 0,
            "tokens_out": usage.get("completion_tokens") or usage.get("output_tokens") or 0,
        }
    except Exception:  # tracing must never break the request
        return {}


@contextmanager
def trace_run(session_id: str = "", request_id: str = ""):
    """Open a trace for one request.

    Usage:
        with trace_run(session_id) as tracer:
            await chat_graph.ainvoke(state, config={..., "callbacks": [tracer]})
            logger.info("run %s", tracer.summary())
    """
    tracer = TraceHandler(session_id=session_id, request_id=request_id)
    token = _current_trace.set(tracer.spans)
    try:
        yield tracer
    finally:
        _current_trace.reset(token)


def get_trace() -> list[dict]:
    """Spans recorded so far for the in-flight request (empty outside a trace)."""
    return list(_current_trace.get() or [])

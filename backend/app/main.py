import warnings
warnings.filterwarnings(
    "ignore",
    message="Expected `none` but got",
    category=UserWarning,
    module="pydantic",
)

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.routes import (
    admin,
    agreements,
    ai,
    appointments,
    auth,
    bail,
    billing,
    calculators,
    cases,
    causelist,
    citator,
    documents,
    engagements,
    inheritance,
    intake,
    lawyers,
    notifications,
    overseas,
    payments,
    users,
    voice,
    whatsapp,
)
from app.core.config import settings
from app.core.logging import RequestIdMiddleware, setup_logging

# Configure logging before anything emits a record.
setup_logging()
from app.core.exceptions import (
    generic_exception_handler,
    http_exception_handler,
    rate_limit_handler,
)
from app.core.rate_limit import limiter
from app.db.chroma import close_chroma, connect_chroma
from app.db.indexes import create_all_indexes
from app.db.mongodb import close_db, connect_db
from app.websockets import chat_socket, notification_socket


async def _causelist_scheduler():
    """Sweep all cause-list watches on an interval (default 6h). The court
    updates its lists in the evening; a few sweeps a day is plenty.

    Every worker runs this loop; a Redis period-lock ensures exactly one worker
    performs each sweep. TTL (55m) covers a sweep but is far under the interval,
    so a dead worker's claim auto-frees before the next period."""
    import asyncio
    import logging
    from app.core.redis_client import acquire_period_lock
    from app.services.causelist_service import check_all_watches

    interval = getattr(settings, "causelist_check_hours", 6) * 3600
    while True:
        try:
            await asyncio.sleep(interval)
            if await acquire_period_lock("lock:scheduler:causelist", ttl_seconds=55 * 60):
                await check_all_watches()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("Cause-list scheduler sweep failed")


async def _poa_expiry_scheduler():
    """Daily sweep: warn on POAs nearing expiry and expire past-due ones.

    Redis period-lock coordinates a single sweep across workers (see
    :func:`_causelist_scheduler`)."""
    import asyncio
    import logging
    from app.core.redis_client import acquire_period_lock
    from app.services.overseas_service import check_expiring

    while True:
        try:
            await asyncio.sleep(24 * 3600)
            if await acquire_period_lock("lock:scheduler:poa", ttl_seconds=3600):
                await check_expiring()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("POA expiry scheduler sweep failed")


async def _warmup_models():
    """Heavy AI warmups (Whisper STT + intent embeddings). Runs in the background
    so startup and health checks aren't blocked and a model failure can't take
    down the whole API."""
    import logging
    try:
        from app.services.whisper_service import whisper_service
        await whisper_service.warmup()
        from app.ai.intent import warmup as intent_warmup
        await intent_warmup()
    except Exception:
        logging.getLogger(__name__).exception("Background model warmup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio

    from app.core.redis_client import close_redis, redis_enabled

    await connect_db()
    await create_all_indexes()
    connect_chroma()
    from app.services.notification_service import set_ws_manager
    from app.websockets.manager import notification_manager
    set_ws_manager(notification_manager)

    warmup_task = _asyncio.create_task(_warmup_models())

    # Cross-worker WebSocket fan-out: every worker subscribes so a notification
    # created on any worker reaches the client on whichever worker holds its
    # socket. No-op when Redis is disabled.
    ws_subscriber_task = _asyncio.create_task(notification_manager.run_subscriber())

    # Schedulers: with Redis, every worker runs the loop and a distributed lock
    # keeps each sweep single-fire (survives a worker dying). Without Redis,
    # fall back to the RUN_SCHEDULERS gate (set false on all but one worker).
    scheduler_tasks = []
    if redis_enabled() or settings.run_schedulers:
        scheduler_tasks = [
            _asyncio.create_task(_causelist_scheduler()),
            _asyncio.create_task(_poa_expiry_scheduler()),
        ]
    yield
    warmup_task.cancel()
    ws_subscriber_task.cancel()
    for task in scheduler_tasks:
        task.cancel()
    await close_redis()
    await close_db()
    close_chroma()


app = FastAPI(
    title="Attorney.AI API",
    version="1.0.0",
    description="AI-powered legal assistance platform for Pakistani citizens",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

_base = settings.frontend_url.rstrip("/")
_cors_origins = {
    _base,
    _base.replace("localhost", "127.0.0.1"),
    _base.replace("127.0.0.1", "localhost"),
}
# Extra origins (apex + www, staging, etc.) from CORS_ORIGINS, comma-separated.
for _extra in settings.cors_origins.split(","):
    _extra = _extra.strip().rstrip("/")
    if _extra:
        _cors_origins.add(_extra)
_cors_origins = list(_cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Outermost middleware (added last) — binds the request id before anything else
# runs, so every downstream log line during the request carries it.
app.add_middleware(RequestIdMiddleware)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(Exception, generic_exception_handler)

API_PREFIX = "/api/v1"

app.include_router(ai.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(cases.router, prefix=API_PREFIX)
app.include_router(intake.router, prefix=API_PREFIX)
app.include_router(lawyers.router, prefix=API_PREFIX)
app.include_router(documents.router, prefix=API_PREFIX)
app.include_router(inheritance.router, prefix=API_PREFIX)
app.include_router(agreements.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(voice.router, prefix=API_PREFIX)
app.include_router(appointments.router, prefix=API_PREFIX)
app.include_router(engagements.router, prefix=API_PREFIX)
app.include_router(causelist.router, prefix=API_PREFIX)
app.include_router(whatsapp.router, prefix=API_PREFIX)
app.include_router(citator.router, prefix=API_PREFIX)
app.include_router(payments.router, prefix=API_PREFIX)
app.include_router(payments.webhook_router, prefix=API_PREFIX)
app.include_router(billing.router, prefix=API_PREFIX)
app.include_router(overseas.router, prefix=API_PREFIX)
app.include_router(calculators.router, prefix=API_PREFIX)
app.include_router(bail.router, prefix=API_PREFIX)

app.include_router(chat_socket.router)
app.include_router(notification_socket.router)


@app.get("/", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "Attorney.AI API"}

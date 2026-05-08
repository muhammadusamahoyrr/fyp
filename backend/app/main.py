from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.routes import (
    admin,
    agreements,
    auth,
    cases,
    documents,
    intake,
    lawyers,
    notifications,
    users,
    voice,
)
from app.core.config import settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await create_all_indexes()
    connect_chroma()
    from app.services.notification_service import set_ws_manager
    from app.websockets.manager import notification_manager
    set_ws_manager(notification_manager)
    from app.services.whisper_service import whisper_service
    await whisper_service.warmup()
    yield
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(Exception, generic_exception_handler)

API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(cases.router, prefix=API_PREFIX)
app.include_router(intake.router, prefix=API_PREFIX)
app.include_router(lawyers.router, prefix=API_PREFIX)
app.include_router(documents.router, prefix=API_PREFIX)
app.include_router(agreements.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
app.include_router(voice.router, prefix=API_PREFIX)

app.include_router(chat_socket.router)
app.include_router(notification_socket.router)


@app.get("/", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "Attorney.AI API"}

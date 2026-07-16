from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    global _client
    _client = AsyncIOMotorClient(
        settings.mongodb_url,
        maxPoolSize=50,               # cap concurrent connections under load
        minPoolSize=5,                # keep warm connections ready
        maxIdleTimeMS=30000,          # recycle idle connections after 30s
        connectTimeoutMS=5000,
        serverSelectionTimeoutMS=5000,  # fail fast instead of hanging if Mongo is down
        retryWrites=True,             # auto-retry transient write failures
    )
    await _client.admin.command("ping")


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client not initialized — call connect_db() first")
    return _client[settings.db_name]


def get_client() -> AsyncIOMotorClient:
    """The Motor client — needed to open sessions for multi-document transactions
    (Atlas is a replica set, so transactions are supported)."""
    if _client is None:
        raise RuntimeError("MongoDB client not initialized — call connect_db() first")
    return _client

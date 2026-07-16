import asyncio
import json
import logging

from fastapi import WebSocket

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

# All workers publish/subscribe on this one channel. Payloads are small JSON
# envelopes: {"target": "user", "user_id": ..., "message": {...}} or
# {"target": "all", "message": {...}}.
_WS_CHANNEL = "attorney:ws"


class ConnectionManager:
    """Tracks live WebSocket connections for this process and fans messages out
    across workers via Redis pub/sub.

    Sockets are inherently process-local (a connection lives in exactly one
    worker), so ``self._connections`` stays in-memory. Cross-worker delivery
    works like this: :meth:`send_to_user` PUBLISHES to a Redis channel; every
    worker runs one :meth:`run_subscriber` task that receives the message and
    delivers it to *its own* local sockets. Because a given socket lives in a
    single worker, it is delivered exactly once — no double-send.

    When Redis is not configured, publish falls back to direct local delivery,
    preserving the original single-process behaviour.
    """

    def __init__(self):
        # user_id → list of active WebSocket connections (multiple tabs)
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(user_id, None)

    # ── Public API (unchanged signatures) ──────────────────────────────────

    async def send_to_user(self, user_id: str, message: dict) -> None:
        """Deliver a message to every connection this user has, on any worker."""
        if not await self._publish({"target": "user", "user_id": user_id, "message": message}):
            await self._deliver_local(user_id, message)

    async def broadcast(self, message: dict) -> None:
        """Deliver a message to every connected user, on any worker."""
        if not await self._publish({"target": "all", "message": message}):
            await self._broadcast_local(message)

    def is_connected(self, user_id: str) -> bool:
        """True if this worker holds a connection for the user. Note: with
        multiple workers this is only local knowledge, not a global answer."""
        return bool(self._connections.get(user_id))

    # ── Redis fan-out ──────────────────────────────────────────────────────

    async def _publish(self, envelope: dict) -> bool:
        """Publish an envelope to the fan-out channel. Returns True if it was
        published to Redis, False if Redis is unavailable (caller should then
        deliver locally)."""
        client = get_redis()
        if client is None:
            return False
        try:
            await client.publish(_WS_CHANNEL, json.dumps(envelope))
            return True
        except Exception:
            logger.exception("Redis publish failed — delivering locally")
            return False

    async def run_subscriber(self) -> None:
        """Subscribe to the fan-out channel and deliver messages to this
        worker's local sockets. Runs for the app's lifetime; start once per
        worker from the lifespan. No-op when Redis is disabled."""
        client = get_redis()
        if client is None:
            return
        while True:
            pubsub = None
            try:
                pubsub = client.pubsub()
                await pubsub.subscribe(_WS_CHANNEL)
                logger.info("WS fan-out subscriber connected")
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(msg["data"])
                    except (ValueError, TypeError):
                        continue
                    await self._dispatch(envelope)
            except asyncio.CancelledError:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass
                raise
            except Exception:
                # Connection dropped — back off and re-subscribe.
                logger.exception("WS fan-out subscriber error; reconnecting in 3s")
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:
                        pass
                await asyncio.sleep(3)

    async def _dispatch(self, envelope: dict) -> None:
        target = envelope.get("target")
        message = envelope.get("message") or {}
        if target == "user":
            await self._deliver_local(envelope.get("user_id", ""), message)
        elif target == "all":
            await self._broadcast_local(message)

    # ── Local delivery ─────────────────────────────────────────────────────

    async def _deliver_local(self, user_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def _broadcast_local(self, message: dict) -> None:
        dead_pairs: list[tuple[str, WebSocket]] = []
        for user_id, conns in list(self._connections.items()):
            for ws in conns:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_pairs.append((user_id, ws))
        for uid, ws in dead_pairs:
            self.disconnect(uid, ws)


notification_manager = ConnectionManager()

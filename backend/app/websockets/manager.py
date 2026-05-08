from fastapi import WebSocket


class ConnectionManager:
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

    async def send_to_user(self, user_id: str, message: dict) -> None:
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                pass

    async def broadcast(self, message: dict) -> None:
        for conns in self._connections.values():
            for ws in conns:
                try:
                    await ws.send_json(message)
                except Exception:
                    pass

    def is_connected(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))


notification_manager = ConnectionManager()

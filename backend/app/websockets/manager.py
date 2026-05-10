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
        dead: list[WebSocket] = []
        for ws in self._connections.get(user_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(user_id, ws)

    async def broadcast(self, message: dict) -> None:
        dead_pairs: list[tuple[str, WebSocket]] = []
        for user_id, conns in self._connections.items():
            for ws in conns:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_pairs.append((user_id, ws))
        for uid, ws in dead_pairs:
            self.disconnect(uid, ws)

    def is_connected(self, user_id: str) -> bool:
        return bool(self._connections.get(user_id))


notification_manager = ConnectionManager()

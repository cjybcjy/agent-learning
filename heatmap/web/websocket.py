from fastapi import WebSocket
import json


class WebSocketManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        # Note: websocket.accept() is called by the route handler before this
        self.connections.setdefault(client_id, []).append(websocket)

    async def disconnect(self, websocket: WebSocket, client_id: str):
        if client_id in self.connections:
            if websocket in self.connections[client_id]:
                self.connections[client_id].remove(websocket)

    async def broadcast(self, message: dict, markets: list[str]):
        for market in markets:
            for ws in self.connections.get(market, []):
                try:
                    await ws.send_text(json.dumps(message))
                except Exception:
                    pass


ws_manager = WebSocketManager()

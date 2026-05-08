import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

LOG = logging.getLogger("heatmap.web.ws")


class WebSocketManager:
    """Manages WebSocket connections with bidirectional subscription tracking."""

    def __init__(self, heartbeat_interval: float = 30.0):
        # market -> set of websockets
        self._market_conns: dict[str, set[WebSocket]] = {}
        # websocket -> set of markets (reverse index for fast cleanup)
        self._conn_markets: dict[WebSocket, set[str]] = {}
        self.heartbeat_interval = heartbeat_interval

    async def connect(self, websocket: WebSocket, market: str) -> None:
        self._market_conns.setdefault(market, set()).add(websocket)
        self._conn_markets.setdefault(websocket, set()).add(market)
        LOG.debug("ws %s subscribed to %s", id(websocket), market)

    async def disconnect(self, websocket: WebSocket, market: str | None = None) -> None:
        if market is None:
            # Remove from all markets
            markets = self._conn_markets.pop(websocket, set())
            for m in markets:
                conns = self._market_conns.get(m)
                if conns:
                    conns.discard(websocket)
                    if not conns:
                        self._market_conns.pop(m, None)
            LOG.debug("ws %s disconnected from all markets", id(websocket))
        else:
            conns = self._market_conns.get(market)
            if conns:
                conns.discard(websocket)
                if not conns:
                    self._market_conns.pop(market, None)
            if websocket in self._conn_markets:
                self._conn_markets[websocket].discard(market)
                if not self._conn_markets[websocket]:
                    self._conn_markets.pop(websocket, None)
            LOG.debug("ws %s unsubscribed from %s", id(websocket), market)

    async def broadcast(self, message: dict, markets: list[str]) -> None:
        text = json.dumps(message)
        dead: list[WebSocket] = []
        for market in markets:
            for ws in list(self._market_conns.get(market, [])):
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
        # Clean up dead connections
        for ws in set(dead):
            await self.disconnect(ws)

    async def heartbeat_loop(self, websocket: WebSocket) -> None:
        """Send periodic heartbeat messages to a single websocket."""
        try:
            while websocket in self._conn_markets:
                await asyncio.sleep(self.heartbeat_interval)
                if websocket not in self._conn_markets:
                    break
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            LOG.exception("heartbeat loop error for ws %s", id(websocket))

    def is_connected(self, websocket: WebSocket) -> bool:
        return websocket in self._conn_markets


ws_manager = WebSocketManager()

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from heatmap.config import load_thresholds
from heatmap.store.dao import Store
from heatmap.web.models import HeatmapResponse, HeatmapItem, ChatRequest
from heatmap.web.websocket import ws_manager

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"

store: Store | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store
    store = Store(DATA / "heatmap.db")
    await store.init()
    yield
    await store.close()
    store = None


app = FastAPI(lifespan=lifespan)


@app.get("/api/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    granularity: str = Query("30min", pattern="^(30min|4h|day|week)$"),
    market: str = Query("all", pattern="^(all|a_share|hk|us|crypto)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None
):
    if store is None:
        return HeatmapResponse(items=[], next_cursor=None)
    if granularity == "week":
        # Week aggregation not yet implemented; fallback to day
        granularity = "day"
    items_raw, next_cursor = await store.get_rollup_heatmap(granularity, market, limit, cursor)
    items = [
        HeatmapItem(
            symbol=r["symbol"],
            rank=idx + 1,
            mention_count=r["mention_count"],
            weighted_score=r["weighted_score"],
        )
        for idx, r in enumerate(items_raw)
    ]
    return HeatmapResponse(items=items, next_cursor=next_cursor)


@app.get("/api/heatmap/{symbol}/trend")
async def get_symbol_trend(symbol: str, granularity: str = "30min"):
    if store is None:
        return {"symbol": symbol, "data": []}
    data = await store.get_rollup_trend(symbol, granularity)
    return {"symbol": symbol, "data": data}


@app.get("/api/heatmap/{symbol}/ai_signals")
async def get_symbol_ai_signals(symbol: str, limit: int = Query(10, ge=1, le=100)):
    if store is None:
        return {"symbol": symbol, "signals": []}
    signals = await store.get_ai_signals_for_symbol(symbol, limit)
    return {"symbol": symbol, "signals": signals}


@app.get("/api/markets")
async def get_markets():
    return {"markets": ["a_share", "hk", "us", "crypto"]}


@app.get("/api/symbols")
async def get_symbols(market: str = Query("all")):
    if store is None:
        return {"market": market, "symbols": []}
    symbols = await store.get_symbols_by_market(market)
    return {"market": market, "symbols": symbols}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    async def event_stream():
        yield f"data: {{'chunk': '思考中...'}}\n\n"
        yield f"data: {{'done': true}}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.websocket("/ws/heatmap")
async def websocket_heatmap(websocket: WebSocket):
    client_id = None
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "subscribe":
                markets = data.get("markets", [])
                for m in markets:
                    await ws_manager.connect(websocket, m)
                client_id = ",".join(markets)
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if client_id:
            for m in client_id.split(","):
                await ws_manager.disconnect(websocket, m)

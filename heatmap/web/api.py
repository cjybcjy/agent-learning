from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from heatmap.web.models import HeatmapResponse, HeatmapItem, ChatRequest

app = FastAPI()


@app.get("/api/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    granularity: str = Query("30min", pattern="^(30min|4h|day|week)$"),
    market: str = Query("all", pattern="^(all|a_share|hk|us|crypto)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None
):
    # TODO: integrate with Store in later tasks
    return HeatmapResponse(items=[], next_cursor=None)


@app.get("/api/heatmap/{symbol}/trend")
async def get_symbol_trend(symbol: str, granularity: str = "30min"):
    return {"symbol": symbol, "data": []}


@app.get("/api/heatmap/{symbol}/ai_signals")
async def get_symbol_ai_signals(symbol: str, limit: int = Query(10, ge=1, le=100)):
    return {"symbol": symbol, "signals": []}


@app.get("/api/markets")
async def get_markets():
    return {"markets": ["a_share", "hk", "us", "crypto"]}


@app.get("/api/symbols")
async def get_symbols(market: str = Query("all")):
    return {"market": market, "symbols": []}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    async def event_stream():
        yield f"data: {{'chunk': '思考中...'}}\n\n"
        yield f"data: {{'done': true}}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")

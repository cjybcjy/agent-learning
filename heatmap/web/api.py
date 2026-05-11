import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import asyncio
import json

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from heatmap.config import load_thresholds
from heatmap.config_store import ConfigStore
from heatmap.store.dao import Store
from heatmap.web.models import HeatmapResponse, HeatmapItem, MarketStatsResponse, MarketStats, ChatRequest, ModelSwitchRequest
from heatmap.web.websocket import ws_manager
from heatmap.ai.chat_engine import ChatEngine
from heatmap.ai.llm_client import get_provider_models, PROVIDERS

LOG = logging.getLogger("heatmap.web.api")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"

store: Store | None = None
chat_engine: ChatEngine | None = None
config_store: ConfigStore | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, chat_engine, config_store
    thresholds = load_thresholds(CONFIG / "thresholds.yaml")
    store = Store(DATA / "heatmap.db")
    await store.init()
    config_store = ConfigStore(DATA / "secrets.yaml")
    chat_engine = ChatEngine(store, thresholds.ai, config_store)
    # Restore persisted active provider if any
    active_provider = config_store.get("ACTIVE_PROVIDER")
    if active_provider and active_provider in PROVIDERS:
        active_model = config_store.get("ACTIVE_MODEL")
        chat_engine.switch_provider(active_provider, active_model)
    yield
    if chat_engine:
        await chat_engine.close()
    await store.close()
    store = None
    chat_engine = None
    config_store = None


app = FastAPI(lifespan=lifespan)


def _compute_confidence(source_count: int, last_updated: str | None) -> float:
    """Compute confidence score (0-100) from source_count and freshness."""
    source_score = min(source_count / 3.0, 1.0) * 100
    if last_updated:
        try:
            # Handle ISO week format (e.g. "2024-W01") — not supported by
            # fromisoformat on Python < 3.11
            if re.match(r'^\d{4}-W\d{2}$', last_updated):
                dt = datetime.strptime(last_updated + '-1', '%Y-W%W-%w').replace(tzinfo=timezone.utc)
            else:
                dt = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            hours_since = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
            freshness_score = max(0.0, 1.0 - hours_since / 24.0)
        except (ValueError, TypeError):
            freshness_score = 0.5
    else:
        freshness_score = 0.5
    return round(source_score * freshness_score, 1)


@app.get("/api/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    granularity: str = Query("30min", pattern="^(30min|4h|day|week)$"),
    market: str = Query("all", pattern="^(all|a_share|hk|us|crypto)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None
):
    if store is None:
        return HeatmapResponse(items=[], next_cursor=None)
    items_raw, next_cursor = await store.get_rollup_heatmap(granularity, market, limit, cursor)

    # Fetch daily scores for buy/sell factors (alpha)
    symbols = [r["symbol"] for r in items_raw]
    daily_scores = await store.get_latest_daily_scores(symbols)

    items = [
        HeatmapItem(
            symbol=r["symbol"],
            rank=idx + 1,
            mention_count=r["mention_count"],
            weighted_score=r["weighted_score"],
            source_count=r.get("source_count", 0),
            last_updated=r.get("window_start"),
            confidence_score=_compute_confidence(
                r.get("source_count", 0),
                r.get("window_start"),
            ),
            instant_alpha=daily_scores.get(r["symbol"], {}).get("alpha"),
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


@app.get("/api/market-stats", response_model=MarketStatsResponse)
async def get_market_stats():
    if store is None:
        return MarketStatsResponse(markets={})
    stats = await store.get_market_stats()
    markets = {
        m: MarketStats(**s) for m, s in stats.items()
    }
    return MarketStatsResponse(markets=markets)


@app.post("/api/chat")
async def chat(request: ChatRequest):
    if chat_engine is None:
        async def error_stream():
            yield f"data: {{'chunk': '服务初始化中...'}}\n\n"
            yield f"data: {{'done': true}}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def event_stream():
        async for chunk in chat_engine.stream_answer(request.question, request.context):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.websocket("/ws/heatmap")
async def websocket_heatmap(websocket: WebSocket):
    await websocket.accept()
    heartbeat_task = asyncio.create_task(ws_manager.heartbeat_loop(websocket))

    async def cleanup():
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        await ws_manager.disconnect(websocket)

    try:
        while True:
            try:
                data = await websocket.receive_json()
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue
            except RuntimeError:
                # FastAPI raises RuntimeError when connection is closed during receive
                break

            action = data.get("action")
            msg_type = data.get("type")

            if action == "subscribe":
                markets = data.get("markets", [])
                for m in markets:
                    await ws_manager.connect(websocket, m)
                await websocket.send_json({"type": "subscribed", "markets": markets})

            elif action == "unsubscribe":
                markets = data.get("markets", [])
                for m in markets:
                    await ws_manager.disconnect(websocket, m)
                await websocket.send_json({"type": "unsubscribed", "markets": markets})

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong", "timestamp": data.get("timestamp")})

    except WebSocketDisconnect:
        pass
    except Exception:
        LOG.exception("websocket error")
    finally:
        await cleanup()


from pydantic import BaseModel

class ConfigUpdate(BaseModel):
    key: str
    value: str

def _provider_key_status() -> dict:
    """Return whether each provider's API key is available (env or config_store)."""
    status = {}
    for name, spec in PROVIDERS.items():
        env_set = bool(os.environ.get(spec.api_key_env))
        store_set = bool(config_store and config_store.get(spec.api_key_env))
        status[name] = {
            "configured": env_set or store_set,
            "source": "env" if env_set else ("store" if store_set else "none"),
            "api_key_env": spec.api_key_env,
        }
    return status


@app.get("/api/config")
async def get_config():
    if config_store is None:
        return {"env_override": True, "keys": {}, "providers": {}}
    return {
        "env_override": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("KIMI_API_KEY") or os.environ.get("BAILIAN_API_KEY")),
        "keys": config_store.get_masked(),
        "providers": _provider_key_status(),
    }

@app.post("/api/config")
async def update_config(body: ConfigUpdate):
    if config_store is None:
        return JSONResponse({"error": "config store not initialized"}, status_code=503)
    config_store.set(body.key, body.value)
    return {"ok": True}


# ── Model / Provider management ──

@app.get("/api/models")
async def get_models():
    return {"providers": get_provider_models()}


@app.get("/api/models/current")
async def get_current_model():
    if chat_engine is None:
        return {"provider": "deepseek", "model": "deepseek-chat", "display_name": "DeepSeek"}
    spec = PROVIDERS.get(chat_engine.config.provider, PROVIDERS["deepseek"])
    return {
        "provider": chat_engine.config.provider,
        "model": chat_engine.config.model,
        "display_name": spec.display_name,
    }


@app.post("/api/models/switch")
async def switch_model(body: ModelSwitchRequest):
    if chat_engine is None:
        return JSONResponse({"error": "chat engine not initialized"}, status_code=503)
    if body.provider not in PROVIDERS:
        return JSONResponse({"error": f"unknown provider: {body.provider}"}, status_code=400)
    chat_engine.switch_provider(body.provider, body.model)
    # Persist selection
    if config_store:
        config_store.set("ACTIVE_PROVIDER", body.provider)
        config_store.set("ACTIVE_MODEL", chat_engine.config.model)
    return {"ok": True, "provider": body.provider, "model": chat_engine.config.model}


# Serve frontend static files (SPA — fallback to index.html for all non-API routes)
app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True), name="static")

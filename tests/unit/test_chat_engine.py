import pytest
from datetime import datetime, timezone

from heatmap.ai.chat_engine import ChatEngine
from heatmap.config import AIConfig
from heatmap.store.dao import Store, RawMessage, Mention


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


@pytest.fixture
def ai_config():
    return AIConfig(model="claude-test", api_key_env="TEST_API_KEY")


@pytest.mark.asyncio
async def test_chat_engine_gather_context_with_symbol(store, ai_config, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "fake")
    engine = ChatEngine(store, ai_config)

    # Seed data
    dt = datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc)
    mid = await store.insert_message(RawMessage(
        platform="tg", channel="@x", author_id="u1",
        content="BTC pump", posted_at=dt, fetched_at=dt,
    ))
    await store.insert_mentions([Mention(mid, "BTC", "btc", False, 1.0)])
    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 100, 100.0, 5)

    ctx = await engine._gather_context({"focused_symbol": "BTC", "market": "crypto"})
    assert "BTC" in ctx
    assert "100" in ctx
    await engine.close()


@pytest.mark.asyncio
async def test_chat_engine_gather_context_empty(store, ai_config):
    engine = ChatEngine(store, ai_config)
    ctx = await engine._gather_context({})
    assert "暂无实时数据" in ctx
    await engine.close()

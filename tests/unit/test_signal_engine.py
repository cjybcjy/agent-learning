import json
from datetime import datetime, timezone
import pytest

from heatmap.aggregator.gates import compute_instant_alpha
from heatmap.ai.cost_guard import CostGuard
from heatmap.ai.prompts import build_prompt
from heatmap.ai.signal_engine import SignalEngine
from heatmap.config import AIConfig
from heatmap.store.dao import Store, RawMessage, Mention


def test_prompt_includes_top_posts():
    posts = [
        {"content": "BTC to the moon", "interactions": 100},
        {"content": "Institutional buying", "interactions": 50},
    ]
    prompt = build_prompt(symbol="BTC", instant_alpha=2.5, sources="twitter", top_posts=posts)
    assert "BTC to the moon" in prompt
    assert "Institutional buying" in prompt
    assert "2.50%" in prompt or "250.00%" in prompt


def test_prompt_includes_json_schema():
    prompt = build_prompt("BTC", 1.0, "twitter", [])
    assert "anomaly_score" in prompt
    assert "sentiment_shift" in prompt
    assert "driver_keywords" in prompt


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


@pytest.fixture
def ai_config():
    return AIConfig(
        instant_alpha_threshold=1.0,
        min_mentions_for_ai=2,
        max_calls_per_day=10,
        model="claude-test",
        api_key_env="TEST_API_KEY",
    )


@pytest.mark.asyncio
async def test_signal_engine_skips_when_alpha_below_threshold(store, ai_config):
    """When instant_alpha is below threshold, no AI call should be made."""
    cost_guard = CostGuard(store, max_calls_per_day=10)
    engine = SignalEngine(store, cost_guard, ai_config)

    # Seed rollup data with low mention count
    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 5, 5.0, 1)

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")
    assert result is None

    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_skips_when_mentions_below_min(store, ai_config):
    """When mention count is below min_mentions_for_ai, skip."""
    cost_guard = CostGuard(store, max_calls_per_day=10)
    engine = SignalEngine(store, cost_guard, ai_config)

    # Seed with high alpha but low mentions
    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 1, 1.0, 1)

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")
    assert result is None

    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_respects_cost_guard(store, ai_config, monkeypatch):
    """When daily budget is exhausted, skip AI call."""
    monkeypatch.setenv("TEST_API_KEY", "fake-key")
    cost_guard = CostGuard(store, max_calls_per_day=1)
    engine = SignalEngine(store, cost_guard, ai_config)

    # Exhaust budget
    await cost_guard.record_call("BTC", "2026-05-02T13:00:00Z", "claude-test")

    # Seed data that would otherwise trigger
    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 100, 100.0, 5)
    # No historical data → instant_alpha = inf (above threshold)

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")
    assert result is None

    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_parses_json_with_code_fence():
    """Test JSON extraction from markdown code blocks."""
    engine = SignalEngine(None, None, AIConfig())
    raw = '```json\n{"anomaly_score": 0.9}\n```'
    parsed = await engine._parse_json(raw)
    assert parsed == {"anomaly_score": 0.9}

    raw2 = "{\"anomaly_score\": 0.8}"
    parsed2 = await engine._parse_json(raw2)
    assert parsed2 == {"anomaly_score": 0.8}

    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_parse_retries_then_fails():
    """Invalid JSON returns None after retries."""
    engine = SignalEngine(None, None, AIConfig())
    parsed = await engine._parse_json("not json", retries=1)
    assert parsed is None
    await engine.close()


def test_compute_instant_alpha_with_historical():
    """EMA-smoothed instant alpha calculation."""
    alpha = compute_instant_alpha(100.0, [50.0, 50.0, 50.0])
    assert alpha == 1.0  # 100/50 - 1 = 1.0

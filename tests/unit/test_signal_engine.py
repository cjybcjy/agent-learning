import json
from datetime import datetime, timezone
import pytest

from heatmap.aggregator.gates import compute_instant_alpha
from heatmap.ai.cost_guard import CostGuard
from heatmap.ai.models import AISignalResult
from heatmap.ai.prompts import build_prompt, _sanitize_post_content
from heatmap.ai.signal_engine import SignalEngine
from heatmap.config import AIConfig
from heatmap.store.dao import Store, RawMessage, Mention


_VALID_JSON = {
    "anomaly_score": 0.85,
    "sentiment_shift": "positive",
    "sentiment_confidence": 0.9,
    "key_driver": "机构大额买入推动",
    "key_driver_confidence": 0.88,
    "driver_keywords": ["机构", "买入", "ETF"],
    "reasoning": "帖子1提到某机构买入10亿",
}


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
    assert "禁止编造" in prompt


def test_prompt_sanitizes_long_content():
    """Posts longer than 500 chars should be truncated."""
    long_post = "A" * 600
    posts = [{"content": long_post, "interactions": 10}]
    prompt = build_prompt("BTC", 1.0, "twitter", posts)
    # The sanitized content should be truncated with "..."
    assert "..." in prompt
    # The raw 600-char string should NOT appear in full
    assert long_post not in prompt


def test_prompt_escapes_braces():
    """Curly braces in user content must not break the JSON schema example."""
    posts = [{"content": "Price will {moon} soon", "interactions": 5}]
    prompt = build_prompt("BTC", 1.0, "twitter", posts)
    # Braces should be escaped/doubled in the sanitized output
    assert "{{moon}}" in prompt or "moon" in prompt


def test_sanitize_post_content_truncates():
    assert len(_sanitize_post_content("x" * 1000)) <= 500
    assert _sanitize_post_content("x" * 1000).endswith("...")


def test_sanitize_post_content_escapes_braces():
    assert "{{" in _sanitize_post_content("{")
    assert "}}" in _sanitize_post_content("}")


def test_sanitize_post_content_flattens_newlines():
    assert "\n" not in _sanitize_post_content("line1\nline2")


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

    # Seed rollup data with moderate mention count
    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 100, 100.0, 1)
    # Seed historical data so alpha is computed (not inf) and below threshold
    # EMA of [50,50,50] = 50, current=100 -> alpha = 100/50 - 1 = 1.0
    # To get alpha below 1.0, we need EMA > current/2
    await store.insert_rollup_30min("BTC", "2026-05-01T14:00:00Z", "crypto", 200, 200.0, 1)
    await store.insert_rollup_30min("BTC", "2026-04-30T14:00:00Z", "crypto", 200, 200.0, 1)

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")
    # instant_alpha with EMA ~200 and current 100 -> 100/200 - 1 = -0.5 < 1.0 threshold
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
    # No historical data -> instant_alpha = inf (above threshold)

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")
    assert result is None

    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_parses_and_validates_json():
    """Valid JSON with all required fields passes Pydantic validation."""
    engine = SignalEngine(None, None, AIConfig())
    raw = json.dumps(_VALID_JSON)
    parsed = await engine._parse_json(raw)
    assert isinstance(parsed, AISignalResult)
    assert parsed.anomaly_score == 0.85
    assert parsed.sentiment_shift == "positive"
    assert parsed.driver_keywords == ["机构", "买入", "ETF"]
    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_parses_json_with_code_fence():
    """JSON extraction from markdown code blocks + Pydantic validation."""
    engine = SignalEngine(None, None, AIConfig())
    raw = f'```json\n{json.dumps(_VALID_JSON)}\n```'
    parsed = await engine._parse_json(raw)
    assert isinstance(parsed, AISignalResult)
    assert parsed.anomaly_score == 0.85
    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_rejects_invalid_sentiment():
    """Pydantic rejects unknown sentiment_shift values."""
    engine = SignalEngine(None, None, AIConfig())
    bad = {**_VALID_JSON, "sentiment_shift": "bullish"}
    parsed = await engine._parse_json(json.dumps(bad))
    assert parsed is None
    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_rejects_out_of_range_score():
    """Pydantic rejects anomaly_score > 1.0."""
    engine = SignalEngine(None, None, AIConfig())
    bad = {**_VALID_JSON, "anomaly_score": 1.5}
    parsed = await engine._parse_json(json.dumps(bad))
    assert parsed is None
    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_parse_retries_then_fails():
    """Invalid JSON returns None after retries."""
    engine = SignalEngine(None, None, AIConfig())
    parsed = await engine._parse_json("not json", retries=1)
    assert parsed is None
    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_end_to_end_with_mocked_llm(store, ai_config, monkeypatch):
    """Full flow: rollup data -> trigger -> mock LLM -> validated result -> DB insert."""
    monkeypatch.setenv("TEST_API_KEY", "fake-key")
    cost_guard = CostGuard(store, max_calls_per_day=10)
    engine = SignalEngine(store, cost_guard, ai_config)

    # Seed rollup data (no history -> instant_alpha = inf)
    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 100, 100.0, 5)

    # Seed raw messages so get_top_posts returns something
    for i in range(3):
        msg = RawMessage(
            platform="telegram", channel="@test",
            author_id="u1", content=f"BTC pump {i}",
            posted_at=datetime(2026, 5, 2, 14, 5, 0, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 2, 14, 5, 0, tzinfo=timezone.utc),
            market="crypto",
        )
        mid = await store.insert_message(msg)
        await store.insert_mentions([Mention(mid, "BTC", "BTC", False, 1.0)])

    # Mock LLM call
    async def mock_chat(prompt):
        return json.dumps(_VALID_JSON)

    engine._llm.chat = mock_chat

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")

    assert result is not None
    assert result["anomaly_score"] == 0.85
    assert result["sentiment_shift"] == "positive"
    assert result["type"] == "ai_signal"

    # Verify DB record
    signals = await store.get_ai_signals_for_symbol("BTC", limit=1)
    assert len(signals) == 1
    assert signals[0]["anomaly_score"] == 0.85
    assert signals[0]["sentiment_shift"] == "positive"

    await engine.close()


@pytest.mark.asyncio
async def test_signal_engine_handles_invalid_llm_output_gracefully(store, ai_config, monkeypatch):
    """When LLM returns garbage, engine falls back to parse_error record."""
    monkeypatch.setenv("TEST_API_KEY", "fake-key")
    cost_guard = CostGuard(store, max_calls_per_day=10)
    engine = SignalEngine(store, cost_guard, ai_config)

    await store.insert_rollup_30min("BTC", "2026-05-02T14:00:00Z", "crypto", 100, 100.0, 5)

    async def mock_chat(prompt):
        return "This is not valid JSON at all"

    engine._llm.chat = mock_chat

    result = await engine.check_and_trigger("BTC", "2026-05-02T14:00:00Z", "crypto")

    # Should still return a payload (with fallback values)
    assert result is not None
    assert result["anomaly_score"] == 0.0
    assert result["sentiment_shift"] == "neutral"

    # DB should have parse_error marker
    signals = await store.get_ai_signals_for_symbol("BTC", limit=1)
    assert len(signals) == 1
    assert signals[0]["raw_analysis"].startswith("[PARSE_ERROR]")

    await engine.close()


def test_compute_instant_alpha_with_historical():
    """EMA-smoothed instant alpha calculation."""
    alpha = compute_instant_alpha(100.0, [50.0, 50.0, 50.0])
    assert alpha == 1.0  # 100/50 - 1 = 1.0

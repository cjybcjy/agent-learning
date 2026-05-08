import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest

from heatmap.aggregator.gates import compute_instant_alpha
from heatmap.aggregator.rollup import RollupEngine
from heatmap.ai.cost_guard import CostGuard
from heatmap.ai.signal_engine import SignalEngine
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry
from heatmap.store.dao import Mention, RawMessage, Store, QueuedMessage
from heatmap.store.writer import BatchWriter
from heatmap.config import AIConfig


@pytest.mark.asyncio
async def test_pipeline_from_queue_to_ai_signal(tmp_path):
    """End-to-end: Queue → BatchWriter → Rollup → AI trigger → ai_signals table."""
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    await store.init()

    try:
        queue = asyncio.Queue()
        writer = BatchWriter(batch_size=2)
        writer_task = asyncio.create_task(writer.run(queue, store))

        extractor = AhoCorasickExtractor([
            AliasEntry("BTC", "BTC", False, "seed"),
        ])

        dt = datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc)
        window_start = "2026-05-02T14:00:00+00:00"

        # Simulate collector putting messages into queue
        for i in range(3):
            msg = RawMessage(
                platform="telegram", channel="@x", author_id="u1",
                content="BTC pump", posted_at=dt, fetched_at=dt,
            )
            hits = extractor.extract(msg.content)
            mentions = [Mention(0, h.symbol, h.matched_alias, h.is_ambiguous, 1.0) for h in hits]
            await queue.put(QueuedMessage(msg, mentions))

        await asyncio.sleep(0.5)
        writer_task.cancel()
        try:
            await writer_task
        except asyncio.CancelledError:
            pass

        # Run rollup
        engine = RollupEngine(store)
        await engine.compute_rollup_30min(window_start, "2026-05-02T14:30:00+00:00")

        # Verify rollup
        rows = await store.get_rollup_30min("BTC", window_start)
        assert len(rows) == 1
        assert rows[0]["mention_count"] == 3

        # Verify instant alpha triggers (no historical data → inf)
        instant_alpha = compute_instant_alpha(3.0, [])
        assert instant_alpha == float('inf')

        # Test AI signal engine with mocked LLM
        ai_config = AIConfig(
            instant_alpha_threshold=1.0,
            min_mentions_for_ai=1,
            max_calls_per_day=10,
            model="claude-test",
            api_key_env="TEST_API_KEY",
        )
        cost_guard = CostGuard(store, max_calls_per_day=10)

        with patch.dict("os.environ", {"TEST_API_KEY": "fake"}):
            signal_engine = SignalEngine(store, cost_guard, ai_config)
            with patch.object(signal_engine._llm, "chat", return_value='{"anomaly_score": 0.95, "sentiment_shift": "positive", "sentiment_confidence": 0.9, "key_driver": "fundamental", "key_driver_confidence": 0.85, "driver_keywords": ["机构买入"], "reasoning": "test"}'):
                result = await signal_engine.check_and_trigger("BTC", window_start, "crypto")

        assert result is not None
        assert result["anomaly_score"] == 0.95
        assert result["sentiment_shift"] == "positive"

        # Verify ai_signals table
        signals = await store.get_ai_signals_for_symbol("BTC", limit=1)
        assert len(signals) == 1
        assert signals[0]["anomaly_score"] == 0.95

        await signal_engine.close()

    finally:
        await store.close()

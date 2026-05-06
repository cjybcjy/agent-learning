import asyncio
from datetime import datetime, timezone

import pytest

from heatmap.aggregator.rollup import RollupEngine
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry
from heatmap.store.dao import Mention, RawMessage, Store
from heatmap.store.writer import BatchWriter


@pytest.mark.asyncio
async def test_full_pipeline_from_raw_to_rollup(tmp_path):
    # Setup
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    await store.init()

    try:
        queue = asyncio.Queue()
        # batch_size=2 with 3 messages tests partial batch flush on cancellation
        writer = BatchWriter(batch_size=2)
        writer_task = asyncio.create_task(writer.run(queue, store))

        extractor = AhoCorasickExtractor([
            AliasEntry("BTC", "BTC", False, "seed"),
        ])

        # Simulate collector putting messages into queue
        dt = datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc)
        window_start = "2026-05-02T14:00:00+00:00"
        for _ in range(3):
            msg = RawMessage(
                platform="telegram", channel="@x", author_id="u1",
                content="BTC pump", posted_at=dt, fetched_at=dt
            )
            await queue.put(msg)

        await asyncio.sleep(0.5)
        writer_task.cancel()
        try:
            await writer_task
        except asyncio.CancelledError:
            pass

        # Run extractor on inserted messages
        cur = await store._db.execute("SELECT id, content FROM raw_messages")
        rows = await cur.fetchall()
        assert len(rows) == 3
        for mid, content in rows:
            hits = extractor.extract(content)
            if hits:
                await store.insert_mentions([
                    Mention(mid, h.symbol, h.matched_alias, h.is_ambiguous, 1.0)
                    for h in hits
                ])

        # Run rollup
        engine = RollupEngine(store)
        await engine.compute_rollup_30min(window_start, "2026-05-02T14:30:00+00:00")

        # Verify
        rows = await store.get_rollup_30min("BTC", window_start)
        assert len(rows) == 1
        assert rows[0]["mention_count"] == 3
        assert rows[0]["weighted_score"] == 3.0
        assert rows[0]["source_count"] == 1
        assert rows[0]["market"] == "crypto"
    finally:
        await store.close()

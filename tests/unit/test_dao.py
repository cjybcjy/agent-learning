import asyncio

import pytest
from datetime import datetime, timezone
from heatmap.store.dao import Store, RawMessage, Mention

@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()

async def test_insert_and_query_message(store):
    msg = RawMessage(
        platform="telegram", channel="@x", author_id="u1",
        content="$DOGE to the moon", posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
        fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
    )
    msg_id = await store.insert_message(msg)
    assert msg_id > 0

async def test_insert_mentions_and_count(store):
    msg_id = await store.insert_message(RawMessage(
        platform="telegram", channel="@x", author_id="u1",
        content="DOGE", posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
        fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
    ))
    await store.insert_mentions([Mention(message_id=msg_id, symbol="DOGE",
        matched_alias="DOGE", is_ambiguous=False, confidence=1.0)])
    counts = await store.daily_mention_counts("2026-04-30")
    assert counts["DOGE"] == 1


async def test_concurrent_inserts_preserve_message_ids(store):
    """多 collector 并发写入时，lastrowid 必须与该次 insert 对应（验证写锁）。"""
    async def one(symbol: str, idx: int):
        mid = await store.insert_message(RawMessage(
            platform="telegram", channel=f"@c{idx}", author_id=str(idx),
            content=symbol, posted_at=datetime(2026,4,30,tzinfo=timezone.utc),
            fetched_at=datetime(2026,4,30,tzinfo=timezone.utc),
        ))
        await store.insert_mentions([Mention(mid, symbol, symbol, False, 1.0)])
        return mid

    ids = await asyncio.gather(*[one(f"S{i}", i) for i in range(50)])
    assert len(set(ids)) == 50  # all unique, no collisions
    counts = await store.daily_mention_counts("2026-04-30")
    assert sum(counts.values()) == 50


async def test_rollup_30min_table_exists(store):
    cur = await store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rollup_30min'"
    )
    row = await cur.fetchone()
    assert row is not None

async def test_ai_signals_table_exists(store):
    cur = await store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_signals'"
    )
    row = await cur.fetchone()
    assert row is not None

async def test_ai_call_log_table_exists(store):
    cur = await store._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ai_call_log'"
    )
    row = await cur.fetchone()
    assert row is not None

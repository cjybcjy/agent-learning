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


async def test_rollup_30min_roundtrip(store):
    await store._db.execute(
        "INSERT INTO rollup_30min(symbol,window_start,market,mention_count,weighted_score,source_count)"
        " VALUES (?,?,?,?,?,?)",
        ("BTC", "2026-05-02T14:00:00Z", "crypto", 10, 10.0, 2)
    )
    await store._db.commit()
    cur = await store._db.execute(
        "SELECT mention_count FROM rollup_30min WHERE symbol=? AND window_start=?",
        ("BTC", "2026-05-02T14:00:00Z")
    )
    row = await cur.fetchone()
    assert row[0] == 10

async def test_rollup_4h_roundtrip(store):
    await store._db.execute(
        "INSERT INTO rollup_4h(symbol,window_start,market,mention_count,weighted_score,source_count)"
        " VALUES (?,?,?,?,?,?)",
        ("BTC", "2026-05-02T12:00:00Z", "crypto", 40, 40.0, 3)
    )
    await store._db.commit()
    cur = await store._db.execute(
        "SELECT mention_count FROM rollup_4h WHERE symbol=? AND window_start=?",
        ("BTC", "2026-05-02T12:00:00Z")
    )
    row = await cur.fetchone()
    assert row[0] == 40

async def test_rollup_daily_roundtrip(store):
    await store._db.execute(
        "INSERT INTO rollup_daily(symbol,date,market,mention_count,weighted_score,source_count)"
        " VALUES (?,?,?,?,?,?)",
        ("BTC", "2026-05-02", "crypto", 200, 200.0, 5)
    )
    await store._db.commit()
    cur = await store._db.execute(
        "SELECT mention_count FROM rollup_daily WHERE symbol=? AND date=?",
        ("BTC", "2026-05-02")
    )
    row = await cur.fetchone()
    assert row[0] == 200

async def test_ai_signals_roundtrip(store):
    await store._db.execute(
        "INSERT INTO ai_signals(symbol,window_start,model_version,created_at,anomaly_score,driver_keywords)"
        " VALUES (?,?,?,?,?,?)",
        ("BTC", "2026-05-02T14:00:00Z", "v1", "2026-05-02T14:05:00Z", 0.9, '["美联储"]')
    )
    await store._db.commit()
    cur = await store._db.execute(
        "SELECT anomaly_score FROM ai_signals WHERE symbol=? AND window_start=?",
        ("BTC", "2026-05-02T14:00:00Z")
    )
    row = await cur.fetchone()
    assert row[0] == 0.9

async def test_ai_call_log_roundtrip(store):
    await store._db.execute(
        "INSERT INTO ai_call_log(symbol,window_start,model_version,called_at)"
        " VALUES (?,?,?,?)",
        ("BTC", "2026-05-02T14:00:00Z", "v1", "2026-05-02T14:05:00Z")
    )
    await store._db.commit()
    cur = await store._db.execute(
        "SELECT COUNT(*) FROM ai_call_log WHERE symbol=?",
        ("BTC",)
    )
    row = await cur.fetchone()
    assert row[0] == 1

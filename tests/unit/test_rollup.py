import pytest
from datetime import datetime, timezone
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.aggregator.rollup import RollupEngine
from heatmap.aggregator.gates import compute_instant_alpha, _ema


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


async def test_rollup_30min_computes_correctly(store):
    dt = datetime(2026, 5, 2, 14, 0, 0, tzinfo=timezone.utc)
    for _ in range(3):
        mid = await store.insert_message(RawMessage(
            platform="telegram", channel="@x", author_id="u1",
            content="BTC pump", posted_at=dt, fetched_at=dt
        ))
        await store.insert_mentions([Mention(mid, "BTC", "btc", False, 1.0)])

    engine = RollupEngine(store)
    await engine.compute_rollup_30min("2026-05-02T14:00:00+00:00", "2026-05-02T14:30:00+00:00")

    rows = await store.get_rollup_30min("BTC", "2026-05-02T14:00:00+00:00")
    assert len(rows) == 1
    assert rows[0]["mention_count"] == 3


async def test_rollup_daily_from_4h(store):
    # Seed rollup_4h data
    for hour in [0, 4, 8, 12, 16, 20]:
        await store._db.execute(
            "INSERT INTO rollup_4h(symbol,window_start,market,mention_count,weighted_score,source_count)"
            " VALUES (?,?,?,?,?,?)",
            ("BTC", f"2026-05-02T{hour:02d}:00:00Z", "crypto", 10, 10.0, 2)
        )
    await store._db.commit()

    engine = RollupEngine(store)
    await engine.compute_rollup_daily("2026-05-02")

    cur = await store._db.execute(
        "SELECT mention_count FROM rollup_daily WHERE symbol=? AND date=?",
        ("BTC", "2026-05-02")
    )
    row = await cur.fetchone()
    assert row[0] == 60  # 6 * 10


def test_ema_computation():
    values = [10.0, 20.0, 30.0]
    result = _ema(values, span=7)
    assert result > 0


def test_compute_instant_alpha():
    alpha = compute_instant_alpha(100.0, [50.0, 50.0, 50.0])
    assert alpha == 1.0  # 100/50 - 1 = 1.0 (100% increase)

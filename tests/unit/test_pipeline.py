import pytest
from datetime import datetime
from heatmap.store.dao import Store, RawMessage, Mention
from heatmap.aggregator.pipeline import run_daily_aggregation


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


async def _seed(store, symbol: str, n: int, day: str):
    dt = datetime.fromisoformat(day + "T12:00:00+00:00")
    for _ in range(n):
        mid = await store.insert_message(RawMessage(
            platform="telegram", channel="@x", author_id=None,
            content=symbol, posted_at=dt, fetched_at=dt,
        ))
        await store.insert_mentions([Mention(mid, symbol, symbol.lower(), False, 1.0)])


async def test_pipeline_picks_surging_symbol(store):
    await _seed(store, "AAA", n=2, day="2026-04-29")
    await _seed(store, "AAA", n=10, day="2026-04-30")
    await _seed(store, "BBB", n=1, day="2026-04-30")
    top = await run_daily_aggregation(store, date="2026-04-30",
                                      alpha_min=0.5, beta_min=1.5,
                                      stage_a_top_n=50, stage_b_top_n=10)
    assert top[0].symbol == "AAA"


async def test_pipeline_persists_all_candidates(store):
    await _seed(store, "AAA", n=2, day="2026-04-29")
    await _seed(store, "AAA", n=10, day="2026-04-30")
    await _seed(store, "BBB", n=1, day="2026-04-30")
    await run_daily_aggregation(store, date="2026-04-30",
                                alpha_min=0.5, beta_min=1.5,
                                stage_a_top_n=50, stage_b_top_n=10)
    # both qualified and unqualified are persisted
    assert await store.get_weighted_score("AAA", "2026-04-30") is not None
    assert await store.get_weighted_score("BBB", "2026-04-30") is not None


async def test_pipeline_empty_day_returns_empty(store):
    top = await run_daily_aggregation(store, date="2026-04-30",
                                      alpha_min=0.5, beta_min=1.5,
                                      stage_a_top_n=50, stage_b_top_n=10)
    assert top == []

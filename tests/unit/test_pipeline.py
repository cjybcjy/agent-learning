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


async def test_pipeline_unqualified_persisted_with_null_composite(store):
    """未达双闸门的候选 composite 必须存 NULL，避免被误读为 0。"""
    # AAA 飙升 → 入选；BBB 平稳低量 → 出局
    await _seed(store, "AAA", n=2, day="2026-04-29")
    await _seed(store, "AAA", n=20, day="2026-04-30")
    await _seed(store, "BBB", n=5, day="2026-04-29")
    await _seed(store, "BBB", n=2, day="2026-04-30")
    await run_daily_aggregation(store, date="2026-04-30",
                                alpha_min=0.5, beta_min=1.5,
                                stage_a_top_n=50, stage_b_top_n=10)
    db = store._db
    cur = await db.execute("SELECT symbol, composite FROM daily_scores WHERE date='2026-04-30'")
    rows = {r[0]: r[1] for r in await cur.fetchall()}
    assert rows["AAA"] is not None and rows["AAA"] > 0
    assert rows["BBB"] is None


async def test_pipeline_market_avg_uses_full_market(store):
    """β 必须基于全市场 weighted 平均；Stage A 截断不能影响平均值。"""
    # 1 个热门 + 大量长尾低频项；若 market_avg 只用 top 50，平均会被热门拉高 → β 偏低
    await _seed(store, "HOT", n=100, day="2026-04-30")
    for i in range(60):  # 60 个长尾，超过 stage_a_top_n=50
        await _seed(store, f"TAIL{i}", n=1, day="2026-04-30")
    # 全市场: (100 + 60*1)/61 ≈ 2.62 → β_HOT ≈ 100/2.62 ≈ 38
    # 若错误地只用 top 50: ≈ (100+49)/50 ≈ 2.98 → β ≈ 33
    top = await run_daily_aggregation(store, date="2026-04-30",
                                      alpha_min=-1.0, beta_min=1.5,  # alpha 放宽以聚焦 β
                                      stage_a_top_n=50, stage_b_top_n=10)
    hot = next(c for c in top if c.symbol == "HOT")
    assert hot.beta > 35  # 全市场口径下应 > 35

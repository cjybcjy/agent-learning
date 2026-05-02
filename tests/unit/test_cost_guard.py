import pytest
from heatmap.ai.cost_guard import CostGuard
from heatmap.store.dao import Store


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.db")
    await s.init()
    yield s
    await s.close()


async def test_cost_guard_allows_within_limit(store):
    guard = CostGuard(store, max_calls_per_day=3)
    assert await guard.can_call("2026-05-02") is True


async def test_cost_guard_blocks_when_exceeded(store):
    guard = CostGuard(store, max_calls_per_day=2)
    await guard.record_call("BTC", "2026-05-02T14:00:00Z", "v1")
    await guard.record_call("ETH", "2026-05-02T14:00:00Z", "v1")
    assert await guard.can_call("2026-05-02") is False


async def test_cost_guard_record_call(store):
    guard = CostGuard(store, max_calls_per_day=10)
    await guard.record_call("BTC", "2026-05-02T14:00:00Z", "claude-v1")
    count = await store.get_ai_call_count_today("2026-05-02")
    assert count == 1

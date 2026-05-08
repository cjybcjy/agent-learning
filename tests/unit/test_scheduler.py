import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from heatmap.scheduler import (
    _next_30min_boundary,
    RollupScheduler,
    AIScheduler,
)


# ── _next_30min_boundary tests (existing) ──

def test_next_30min_boundary_rounds_up():
    now = datetime(2026, 5, 1, 14, 15, 0, tzinfo=timezone.utc)
    assert _next_30min_boundary(now) == datetime(2026, 5, 1, 14, 30, 0, tzinfo=timezone.utc)


def test_next_30min_boundary_crosses_hour():
    now = datetime(2026, 5, 1, 14, 45, 0, tzinfo=timezone.utc)
    assert _next_30min_boundary(now) == datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)


def test_next_30min_boundary_at_exact_boundary():
    now = datetime(2026, 5, 1, 14, 30, 0, tzinfo=timezone.utc)
    assert _next_30min_boundary(now) == datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)


# ── RollupScheduler boundary tests ──

def _make_sleep_controlled():
    """Return a sleep mock that succeeds on first call, raises CancelledError on second."""
    call_count = 0
    async def fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()
    return fake_sleep


@pytest.mark.asyncio
async def test_rollup_scheduler_computes_30min_window():
    """RollupScheduler calls compute_rollup_30min with correct 30-minute window."""
    store = MagicMock()
    engine = AsyncMock()
    completion_queue = asyncio.Queue()

    scheduler = RollupScheduler(store, engine, completion_queue)

    with patch("heatmap.scheduler.asyncio.sleep", _make_sleep_controlled()):
        with patch("heatmap.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 14, 15, 0, tzinfo=timezone.utc)
            # Allow datetime() constructor to still work inside the module
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else mock_dt.now.return_value
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                pass

    engine.compute_rollup_30min.assert_awaited_once()
    args = engine.compute_rollup_30min.await_args.args
    assert args[0] == "2026-05-01T14:00:00Z"
    assert args[1] == "2026-05-01T14:30:00Z"


@pytest.mark.asyncio
async def test_rollup_scheduler_triggers_4h_at_boundary():
    """At 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC, also trigger 4h rollup."""
    store = MagicMock()
    engine = AsyncMock()
    completion_queue = asyncio.Queue()
    scheduler = RollupScheduler(store, engine, completion_queue)

    with patch("heatmap.scheduler.asyncio.sleep", _make_sleep_controlled()):
        with patch("heatmap.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 3, 55, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else mock_dt.now.return_value
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                pass

    # 30min rollup for 03:30-04:00
    engine.compute_rollup_30min.assert_awaited_once()
    # 4h rollup for 00:00-04:00
    engine.compute_rollup_4h.assert_awaited_once_with("2026-05-01T00:00:00Z")
    # Should NOT trigger daily (04:00 is not midnight)
    engine.compute_rollup_daily.assert_not_awaited()


@pytest.mark.asyncio
async def test_rollup_scheduler_triggers_daily_at_midnight():
    """At 00:00 UTC, also trigger daily rollup for the previous day."""
    store = MagicMock()
    engine = AsyncMock()
    completion_queue = asyncio.Queue()
    scheduler = RollupScheduler(store, engine, completion_queue)

    with patch("heatmap.scheduler.asyncio.sleep", _make_sleep_controlled()):
        with patch("heatmap.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 23, 55, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else mock_dt.now.return_value
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                pass

    # 30min rollup for 23:30-00:00
    engine.compute_rollup_30min.assert_awaited_once()
    # Daily rollup for 2026-05-01 (the day that just ended)
    engine.compute_rollup_daily.assert_awaited_once_with("2026-05-01")
    # Also 4h rollup since 00:00 is a 4h boundary
    engine.compute_rollup_4h.assert_awaited_once_with("2026-05-01T20:00:00Z")


@pytest.mark.asyncio
async def test_rollup_scheduler_puts_completion_on_queue():
    """After successful rollup, window_start is put on completion_queue for AI."""
    store = MagicMock()
    engine = AsyncMock()
    completion_queue = asyncio.Queue()
    scheduler = RollupScheduler(store, engine, completion_queue)

    with patch("heatmap.scheduler.asyncio.sleep", _make_sleep_controlled()):
        with patch("heatmap.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 14, 15, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else mock_dt.now.return_value
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                pass

    assert completion_queue.qsize() == 1
    assert completion_queue.get_nowait() == "2026-05-01T14:00:00Z"


@pytest.mark.asyncio
async def test_rollup_scheduler_continues_on_rollup_failure():
    """If compute_rollup_30min raises, scheduler logs and continues (next loop iteration)."""
    store = MagicMock()
    engine = AsyncMock()
    engine.compute_rollup_30min.side_effect = RuntimeError("db locked")
    completion_queue = asyncio.Queue()
    scheduler = RollupScheduler(store, engine, completion_queue)

    with patch("heatmap.scheduler.asyncio.sleep", _make_sleep_controlled()):
        with patch("heatmap.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 14, 15, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else mock_dt.now.return_value
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                pass

    # Failure should NOT put anything on completion queue
    assert completion_queue.qsize() == 0
    # But it should have tried
    engine.compute_rollup_30min.assert_awaited_once()


@pytest.mark.asyncio
async def test_rollup_scheduler_midnight_crossing_date():
    """Daily rollup date must be the previous day when crossing midnight."""
    store = MagicMock()
    engine = AsyncMock()
    completion_queue = asyncio.Queue()
    scheduler = RollupScheduler(store, engine, completion_queue)

    with patch("heatmap.scheduler.asyncio.sleep", _make_sleep_controlled()):
        with patch("heatmap.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 23, 55, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw) if a else mock_dt.now.return_value
            try:
                await scheduler.run()
            except asyncio.CancelledError:
                pass

    # Daily rollup should be for May 1 (the day that ended), not May 2
    engine.compute_rollup_daily.assert_awaited_once_with("2026-05-01")


# ── AIScheduler tests ──

@pytest.mark.asyncio
async def test_ai_scheduler_triggers_for_each_symbol_in_window():
    """AIScheduler reads symbols from rollup_30min and calls check_and_trigger for each."""
    store = MagicMock()
    store._db = AsyncMock()

    # Mock cursor returning 2 symbols
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=(("BTC", "crypto"), ("ETH", "crypto")))
    store._db.execute = AsyncMock(return_value=mock_cursor)

    signal_engine = AsyncMock()
    signal_engine.check_and_trigger = AsyncMock(return_value={"anomaly_score": 0.9})

    completion_queue = asyncio.Queue()
    scheduler = AIScheduler(store, signal_engine, completion_queue)

    # Put a window on the queue, then cancel after processing
    await completion_queue.put("2026-05-01T14:00:00Z")

    async def cancel_after_delay():
        await asyncio.sleep(0.1)
        scheduler_task.cancel()

    scheduler_task = asyncio.create_task(scheduler.run())
    canceller = asyncio.create_task(cancel_after_delay())

    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await canceller
    except asyncio.CancelledError:
        pass

    store._db.execute.assert_awaited_once()
    call_args = store._db.execute.await_args.args
    assert call_args[1] == ("2026-05-01T14:00:00Z",)

    assert signal_engine.check_and_trigger.await_count == 2
    signal_engine.check_and_trigger.assert_any_call("BTC", "2026-05-01T14:00:00Z", "crypto")
    signal_engine.check_and_trigger.assert_any_call("ETH", "2026-05-01T14:00:00Z", "crypto")


@pytest.mark.asyncio
async def test_ai_scheduler_skips_empty_window():
    """When no symbols exist for a window, AI scheduler does nothing."""
    store = MagicMock()
    store._db = AsyncMock()

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[])
    store._db.execute = AsyncMock(return_value=mock_cursor)

    signal_engine = AsyncMock()
    completion_queue = asyncio.Queue()
    scheduler = AIScheduler(store, signal_engine, completion_queue)

    await completion_queue.put("2026-05-01T14:00:00Z")

    async def cancel_after_delay():
        await asyncio.sleep(0.1)
        scheduler_task.cancel()

    scheduler_task = asyncio.create_task(scheduler.run())
    canceller = asyncio.create_task(cancel_after_delay())

    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await canceller
    except asyncio.CancelledError:
        pass

    signal_engine.check_and_trigger.assert_not_awaited()


@pytest.mark.asyncio
async def test_ai_scheduler_isolates_per_symbol_failure():
    """If check_and_trigger fails for one symbol, others still process."""
    store = MagicMock()
    store._db = AsyncMock()

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=(("BTC", "crypto"), ("ETH", "crypto")))
    store._db.execute = AsyncMock(return_value=mock_cursor)

    signal_engine = AsyncMock()
    signal_engine.check_and_trigger = AsyncMock(side_effect=[
        Exception("LLM timeout"),
        {"anomaly_score": 0.8},
    ])

    completion_queue = asyncio.Queue()
    scheduler = AIScheduler(store, signal_engine, completion_queue)

    await completion_queue.put("2026-05-01T14:00:00Z")

    async def cancel_after_delay():
        await asyncio.sleep(0.1)
        scheduler_task.cancel()

    scheduler_task = asyncio.create_task(scheduler.run())
    canceller = asyncio.create_task(cancel_after_delay())

    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    try:
        await canceller
    except asyncio.CancelledError:
        pass

    assert signal_engine.check_and_trigger.await_count == 2

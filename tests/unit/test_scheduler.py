from datetime import datetime, timezone

from heatmap.scheduler import _next_daily_run


def test_next_daily_run_uses_today_if_before_cutoff():
    now = datetime(2026, 5, 1, 0, 4, 0, tzinfo=timezone.utc)
    assert _next_daily_run(now) == datetime(2026, 5, 1, 0, 5, 0, tzinfo=timezone.utc)


def test_next_daily_run_uses_tomorrow_if_cutoff_passed():
    now = datetime(2026, 5, 1, 0, 30, 0, tzinfo=timezone.utc)
    assert _next_daily_run(now) == datetime(2026, 5, 2, 0, 5, 0, tzinfo=timezone.utc)
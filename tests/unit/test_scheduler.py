from datetime import datetime, timezone

from heatmap.scheduler import _next_30min_boundary


def test_next_30min_boundary_rounds_up():
    now = datetime(2026, 5, 1, 14, 15, 0, tzinfo=timezone.utc)
    assert _next_30min_boundary(now) == datetime(2026, 5, 1, 14, 30, 0, tzinfo=timezone.utc)


def test_next_30min_boundary_crosses_hour():
    now = datetime(2026, 5, 1, 14, 45, 0, tzinfo=timezone.utc)
    assert _next_30min_boundary(now) == datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)


def test_next_30min_boundary_at_exact_boundary():
    now = datetime(2026, 5, 1, 14, 30, 0, tzinfo=timezone.utc)
    assert _next_30min_boundary(now) == datetime(2026, 5, 1, 15, 0, 0, tzinfo=timezone.utc)

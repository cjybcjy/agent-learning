from datetime import datetime, timedelta, timezone

import pytest


def test_research_data_hub_caches_topic_until_ttl_expires():
    try:
        from sentinel.web.services.research_data_hub_service import (
            DataFetchResult,
            ResearchDataHub,
            TopicPolicy,
        )
    except ImportError:
        pytest.fail("research data hub service is not implemented")

    now = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)
    calls = {"count": 0}

    def clock():
        return now

    def fetch_financials():
        calls["count"] += 1
        return DataFetchResult.success(
            data={"version": calls["count"]},
            source="fake-financials",
            row_count=1,
            watermark=f"v{calls['count']}",
        )

    hub = ResearchDataHub(clock=clock)
    hub.register(
        "financial:600519",
        fetch_financials,
        TopicPolicy(ttl_seconds=600, min_interval_seconds=0),
    )

    first = hub.get_or_fetch("financial:600519")
    second = hub.get_or_fetch("financial:600519")
    now += timedelta(seconds=601)
    third = hub.get_or_fetch("financial:600519")

    assert first.data == {"version": 1}
    assert second.data == {"version": 1}
    assert second.from_cache is True
    assert third.data == {"version": 2}
    assert calls["count"] == 2

    state = hub.state("financial:600519")
    assert state.status == "success"
    assert state.row_count == 1
    assert state.watermark == "v2"
    assert state.last_success_at == now


def test_research_data_hub_keeps_last_known_good_after_fetch_error():
    try:
        from sentinel.web.services.research_data_hub_service import (
            DataFetchResult,
            ResearchDataHub,
            TopicPolicy,
        )
    except ImportError:
        pytest.fail("research data hub service is not implemented")

    calls = {"count": 0}

    def flaky_fetcher():
        calls["count"] += 1
        if calls["count"] == 1:
            return DataFetchResult.success(
                data={"ok": True},
                source="fake-financials",
                row_count=3,
                watermark="2025Q4",
            )
        raise RuntimeError("upstream timeout")

    hub = ResearchDataHub()
    hub.register(
        "financial:600519",
        flaky_fetcher,
        TopicPolicy(ttl_seconds=600, min_interval_seconds=0),
    )

    first = hub.get_or_fetch("financial:600519")
    failed = hub.get_or_fetch("financial:600519", force=True)
    state = hub.state("financial:600519")

    assert first.success is True
    assert failed.success is False
    assert failed.data == {"ok": True}
    assert "upstream timeout" in (failed.error or "")
    assert state.status == "error"
    assert state.row_count == 3
    assert state.last_value == {"ok": True}
    assert "upstream timeout" in state.last_error

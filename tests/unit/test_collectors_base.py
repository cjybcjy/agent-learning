from heatmap.collectors.base import BaseCollector


def test_base_collector_is_protocol_like():
    assert hasattr(BaseCollector, "run")

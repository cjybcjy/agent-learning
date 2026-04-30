from sentinel.collectors.base import StaticCollector
from sentinel.collectors.registry import CollectorRegistry
from sentinel.domain.models import Market


def test_registry_resolves_collectors_for_market() -> None:
    registry = CollectorRegistry()
    registry.register(StaticCollector(market=Market.A_SHARE, platform="xueqiu", mentions=[]))
    registry.register(StaticCollector(market=Market.A_SHARE, platform="eastmoney", mentions=[]))

    collectors = registry.list_for_market(Market.A_SHARE, ["xueqiu"])

    assert len(collectors) == 1
    assert collectors[0].platform == "xueqiu"


def test_registry_raises_for_unknown_collector_key() -> None:
    registry = CollectorRegistry()

    try:
        registry.list_for_market(Market.US, ["reddit_stocks"])
    except KeyError as exc:
        assert "reddit_stocks" in str(exc)
    else:
        raise AssertionError("expected KeyError")

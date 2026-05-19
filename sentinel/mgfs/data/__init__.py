import os

from sentinel.mgfs.data.metrics_aggregator import MetricsAggregator
from sentinel.mgfs.data.price_fetcher import MockPriceFetcher, PriceFetcher
from sentinel.mgfs.data.valuation_fetcher import MockValuationFetcher, ValuationFetcher

__all__ = ["MetricsAggregator", "ValuationFetcher", "MockValuationFetcher", "get_price_fetcher"]


def get_price_fetcher() -> PriceFetcher:
    """Return MultiSourceFetcher with full priority chain."""
    from sentinel.mgfs.data.multi_source_fetcher import MultiSourceFetcher
    return MultiSourceFetcher.default_chain()

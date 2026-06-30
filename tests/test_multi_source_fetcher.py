from __future__ import annotations

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.price_fetcher import OHLCV, PriceFetcher
from sentinel.mgfs.data.multi_source_fetcher import MultiSourceFetcher


class FailingFetcher(PriceFetcher):
    def fetch_ohlcv(self, symbol: str, market: Market, days: int = 120) -> list[OHLCV]:
        raise ConnectionError("simulated failure")


class GoodFetcher(PriceFetcher):
    def fetch_ohlcv(self, symbol: str, market: Market, days: int = 120) -> list[OHLCV]:
        bars: list[OHLCV] = []
        for i in range(days):
            bars.append(
                OHLCV(
                    date=f"202401{i + 1:03d}",
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=1000000,
                )
            )
        return bars


class ShortDataFetcher(PriceFetcher):
    def fetch_ohlcv(self, symbol: str, market: Market, days: int = 120) -> list[OHLCV]:
        bars: list[OHLCV] = []
        for i in range(30):
            bars.append(
                OHLCV(
                    date=f"202401{i + 1:03d}",
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=1000000,
                )
            )
        return bars


def test_fallback_chain_skips_failing_source() -> None:
    fetcher = MultiSourceFetcher([FailingFetcher(), GoodFetcher()])
    result = fetcher.fetch_ohlcv("000001", Market.A_SHARE, days=120)
    assert len(result) == 120


def test_data_poisoning_guard_rejects_short_data() -> None:
    fetcher = MultiSourceFetcher([ShortDataFetcher(), GoodFetcher()])
    result = fetcher.fetch_ohlcv("000001", Market.A_SHARE, days=120)
    assert len(result) == 120


def test_all_sources_failed_raises_runtime_error() -> None:
    fetcher = MultiSourceFetcher([FailingFetcher(), FailingFetcher()])
    with pytest.raises(RuntimeError, match="All 2 sources failed"):
        fetcher.fetch_ohlcv("000001", Market.A_SHARE, days=120)


def test_default_chain_returns_multi_source() -> None:
    fetcher = MultiSourceFetcher.default_chain()
    assert isinstance(fetcher, MultiSourceFetcher)


def test_default_chain_accepts_fast_network_options() -> None:
    fetcher = MultiSourceFetcher.default_chain(
        request_timeout=2.5,
        max_retries=1,
        delay_scale=0.0,
    )

    eastmoney_sources = [
        source
        for source in fetcher._sources
        if source.__class__.__name__ == "EastmoneyKlineFetcher"
    ]
    if eastmoney_sources:
        assert eastmoney_sources[0]._request_timeout == 2.5
        assert eastmoney_sources[0]._max_retries == 1
        assert eastmoney_sources[0]._delay_scale == 0.0

    adapter_sources = [
        source
        for source in fetcher._sources
        if hasattr(source, "_adapter")
    ]
    assert adapter_sources
    for source in adapter_sources:
        assert source._adapter._request_timeout == 2.5
        assert source._adapter._delay_scale == 0.0

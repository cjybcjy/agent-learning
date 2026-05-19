from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.sina_kline_fetcher import SinaKlineFetcher


class TestSinaKlineFetcherParse:
    def test_parse_sina_kline_response(self) -> None:
        raw = [
            {"day": "2024-01-02", "open": "100.0", "high": "101.0", "low": "99.0", "close": "100.5", "volume": "1000000"},
            {"day": "2024-01-03", "open": "100.5", "high": "102.0", "low": "100.0", "close": "101.5", "volume": "2000000"},
        ]
        fetcher = SinaKlineFetcher()
        bars = fetcher._parse(raw)

        assert len(bars) == 2
        assert bars[0].date == "2024-01-02"
        assert bars[0].open == 100.0
        assert bars[0].high == 101.0
        assert bars[0].low == 99.0
        assert bars[0].close == 100.5
        assert bars[0].volume == 1000000

        assert bars[1].date == "2024-01-03"
        assert bars[1].open == 100.5
        assert bars[1].high == 102.0
        assert bars[1].low == 100.0
        assert bars[1].close == 101.5
        assert bars[1].volume == 2000000

    def test_parse_empty_returns_empty(self) -> None:
        fetcher = SinaKlineFetcher()
        assert fetcher._parse([]) == []
        assert fetcher._parse(None) == []


class TestSinaKlineFetcherSymbolToCode:
    def test_symbol_to_sina_code(self) -> None:
        fetcher = SinaKlineFetcher()
        assert fetcher._symbol_to_code("600519", Market.A_SHARE) == "sh600519"
        assert fetcher._symbol_to_code("000001", Market.A_SHARE) == "sz000001"
        assert fetcher._symbol_to_code("5xxxx", Market.A_SHARE) == "sh5xxxx"
        assert fetcher._symbol_to_code("9xxxx", Market.A_SHARE) == "sh9xxxx"


class TestSinaKlineFetcherFetchOHLCV:
    def test_fetch_ohlcv_calls_adapter_and_returns_bars(self) -> None:
        raw = [
            {"day": "2024-01-02", "open": "100.0", "high": "101.0", "low": "99.0", "close": "100.5", "volume": "1000000"},
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = raw

        mock_adapter = MagicMock()
        mock_adapter.get.return_value = mock_resp

        fetcher = SinaKlineFetcher(adapter=mock_adapter)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert len(bars) == 1
        assert bars[0].date == "2024-01-02"
        mock_adapter.get.assert_called_once()
        call_url = mock_adapter.get.call_args[0][0]
        assert "money.finance.sina.com.cn" in call_url
        assert "sh600519" in call_url
        assert "scale=240" in call_url
        assert "datalen=120" in call_url

    def test_fetch_ohlcv_slices_to_days(self) -> None:
        raw = [
            {"day": f"2024-01-{i:02d}", "open": "100.0", "high": "101.0", "low": "99.0", "close": "100.5", "volume": "1000000"}
            for i in range(1, 11)
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = raw

        mock_adapter = MagicMock()
        mock_adapter.get.return_value = mock_resp

        fetcher = SinaKlineFetcher(adapter=mock_adapter)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=5)

        assert len(bars) == 5
        assert bars[0].date == "2024-01-06"
        assert bars[-1].date == "2024-01-10"

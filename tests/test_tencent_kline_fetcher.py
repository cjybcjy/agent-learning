from __future__ import annotations

from sentinel.domain.models import Market
from sentinel.mgfs.data.tencent_kline_fetcher import TencentKlineFetcher


class TestTencentKlineFetcherParse:
    def test_parse_tencent_kline_response(self) -> None:
        raw = {
            "code": "0",
            "data": {
                "sh600519": {
                    "day": [
                        ["2024-01-02", "1725.00", "1730.50", "1718.00", "1735.00", "12345"],
                        ["2024-01-03", "1730.50", "1728.00", "1725.00", "1732.00", "9876"],
                    ]
                }
            }
        }
        fetcher = TencentKlineFetcher()
        bars = fetcher._parse(raw, "sh600519")

        assert len(bars) == 2
        assert bars[0].date == "2024-01-02"
        assert bars[0].open == 1725.0
        assert bars[0].close == 1730.5
        assert bars[0].low == 1718.0
        assert bars[0].high == 1735.0
        assert bars[0].volume == 12345

        assert bars[1].date == "2024-01-03"
        assert bars[1].open == 1730.5
        assert bars[1].close == 1728.0
        assert bars[1].low == 1725.0
        assert bars[1].high == 1732.0
        assert bars[1].volume == 9876

    def test_parse_empty_returns_empty(self) -> None:
        fetcher = TencentKlineFetcher()
        assert fetcher._parse({}, "sh600519") == []
        assert fetcher._parse({"data": {}}, "sh600519") == []
        assert fetcher._parse({"data": {"sh600519": {}}}, "sh600519") == []


class TestTencentKlineFetcherSymbolToCode:
    def test_symbol_to_tencent_code(self) -> None:
        fetcher = TencentKlineFetcher()
        assert fetcher._symbol_to_code("600519", Market.A_SHARE) == "sh600519"
        assert fetcher._symbol_to_code("000001", Market.A_SHARE) == "sz000001"
        assert fetcher._symbol_to_code("5xxxx", Market.A_SHARE) == "sh5xxxx"
        assert fetcher._symbol_to_code("9xxxx", Market.A_SHARE) == "sh9xxxx"

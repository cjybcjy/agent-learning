from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.tushare_fetcher import TushareValuationFetcher


class FakeDataFrame:
    def __init__(self, data: dict[str, list[Any]]) -> None:
        self._data = data

    @property
    def empty(self) -> bool:
        return len(self._data.get("trade_date", [])) == 0

    def sort_values(self, _by: str) -> "FakeDataFrame":
        return self

    def __getitem__(self, key: str) -> list[Any]:
        return self._data[key]


class TestTushareFetcherInit:
    @patch("sentinel.mgfs.data.tushare_fetcher._import_tushare")
    def test_init_without_token_raises(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_import.return_value = mock_ts
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Tushare token is required"):
                fetcher = TushareValuationFetcher(token=None)
                fetcher._get_pro()

    def test_init_with_token_sets_token(self) -> None:
        fetcher = TushareValuationFetcher(token="fake_token")
        assert fetcher._token == "fake_token"


class TestTushareFetcherSymbolConversion:
    def test_shanghai_symbol(self) -> None:
        assert TushareValuationFetcher._symbol_to_ts_code("600519", Market.A_SHARE) == "600519.SH"

    def test_shenzhen_symbol(self) -> None:
        assert TushareValuationFetcher._symbol_to_ts_code("000001", Market.A_SHARE) == "000001.SZ"

    def test_gem_symbol(self) -> None:
        assert TushareValuationFetcher._symbol_to_ts_code("300750", Market.A_SHARE) == "300750.SZ"


class TestTushareFetcherMetricMapping:
    def test_pe_ttm_maps_correctly(self) -> None:
        assert TushareValuationFetcher._metric_to_field("PE_TTM") == "pe_ttm"

    def test_pb_maps_correctly(self) -> None:
        assert TushareValuationFetcher._metric_to_field("PB") == "pb"

    def test_unsupported_metric_raises(self) -> None:
        with pytest.raises(ValueError, match="not supported by Tushare"):
            TushareValuationFetcher._metric_to_field("Operating_CF_Yield")


class TestTushareFetcherFetchHistory:
    @patch("sentinel.mgfs.data.tushare_fetcher._import_tushare")
    def test_fetch_history_returns_values(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": ["20240101", "20240102", "20240103"],
            "pe_ttm": [15.5, 16.2, 15.8],
        })
        mock_pro.daily_basic.return_value = mock_df

        fetcher = TushareValuationFetcher(token="fake_token", seed=42)
        result = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert result == [15.5, 16.2, 15.8]
        mock_pro.daily_basic.assert_called_once()

    @patch("sentinel.mgfs.data.tushare_fetcher._import_tushare")
    def test_fetch_history_empty_returns_empty_list(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({"trade_date": [], "pe_ttm": []})
        mock_pro.daily_basic.return_value = mock_df

        fetcher = TushareValuationFetcher(token="fake_token", seed=42)
        result = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert result == []

    @patch("sentinel.mgfs.data.tushare_fetcher._import_tushare")
    def test_fetch_history_handles_none_values(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": ["20240101", "20240102", "20240103"],
            "pe_ttm": [15.5, None, 15.8],
        })
        mock_pro.daily_basic.return_value = mock_df

        fetcher = TushareValuationFetcher(token="fake_token", seed=42)
        result = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert result == [15.5, -1.0, 15.8]


class TestTushareFetcherRetry:
    @patch("time.sleep")
    @patch("sentinel.mgfs.data.tushare_fetcher._import_tushare")
    def test_retry_on_transient_failure(self, mock_import: Any, mock_sleep: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": ["20240101"],
            "pe_ttm": [20.0],
        })
        # First two calls fail, third succeeds
        mock_pro.daily_basic.side_effect = [
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            mock_df,
        ]

        fetcher = TushareValuationFetcher(token="fake_token", seed=42)
        result = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert result == [20.0]
        assert mock_pro.daily_basic.call_count == 3

    @patch("time.sleep")
    @patch("sentinel.mgfs.data.tushare_fetcher._import_tushare")
    def test_raises_after_max_retries(self, mock_import: Any, mock_sleep: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts
        mock_pro.daily_basic.side_effect = ConnectionError("timeout")

        fetcher = TushareValuationFetcher(token="fake_token", seed=42)
        with pytest.raises(ConnectionError):
            fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert mock_pro.daily_basic.call_count == 3

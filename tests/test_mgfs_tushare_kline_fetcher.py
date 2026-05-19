from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.tushare_kline_fetcher import TushareKlineFetcher


class _FakeRow:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        return self._data[name]


class FakeDataFrame:
    def __init__(self, data: dict[str, list[Any]]) -> None:
        self._data = data

    @property
    def empty(self) -> bool:
        return len(self._data.get("trade_date", [])) == 0

    def sort_values(self, _by: str) -> "FakeDataFrame":
        return self

    def itertuples(self, index: bool = True) -> Any:
        rows = len(self._data.get("trade_date", []))
        for i in range(rows):
            yield _FakeRow({k: v[i] for k, v in self._data.items()})


class TestTushareKlineFetcherInit:
    def test_init_with_token_sets_token(self) -> None:
        fetcher = TushareKlineFetcher(token="fake_token")
        assert fetcher._token == "fake_token"

    @patch("sentinel.mgfs.data.tushare_kline_fetcher._import_tushare")
    def test_init_without_token_raises(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_import.return_value = mock_ts
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Tushare token is required"):
                fetcher = TushareKlineFetcher(token=None)
                fetcher._get_pro()


class TestTushareKlineFetcherFetchOHLCV:
    @patch("sentinel.mgfs.data.tushare_kline_fetcher._import_tushare")
    def test_fetch_ohlcv_returns_bars(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": ["20240101", "20240102", "20240103"],
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [99.0, 100.0, 101.0],
            "close": [101.0, 102.0, 103.0],
            "vol": [10000, 20000, 15000],
        })
        mock_pro.daily.return_value = mock_df

        fetcher = TushareKlineFetcher(token="fake_token", seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert len(bars) == 3
        assert bars[0].date == "20240101"
        assert bars[0].open == 100.0
        assert bars[0].high == 105.0
        assert bars[0].low == 99.0
        assert bars[0].close == 101.0
        assert bars[0].volume == 10000

        mock_pro.daily.assert_called_once()
        call_kwargs = mock_pro.daily.call_args.kwargs
        assert call_kwargs["ts_code"] == "600519.SH"

    @patch("sentinel.mgfs.data.tushare_kline_fetcher._import_tushare")
    def test_fetch_ohlcv_empty_returns_empty_list(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": [],
            "open": [],
            "high": [],
            "low": [],
            "close": [],
            "vol": [],
        })
        mock_pro.daily.return_value = mock_df

        fetcher = TushareKlineFetcher(token="fake_token", seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert bars == []

    @patch("sentinel.mgfs.data.tushare_kline_fetcher._import_tushare")
    def test_fetch_ohlcv_shenzhen_symbol(self, mock_import: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": ["20240101"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "vol": [5000],
        })
        mock_pro.daily.return_value = mock_df

        fetcher = TushareKlineFetcher(token="fake_token", seed=42)
        bars = fetcher.fetch_ohlcv("000001", Market.A_SHARE, days=120)

        assert len(bars) == 1
        call_kwargs = mock_pro.daily.call_args.kwargs
        assert call_kwargs["ts_code"] == "000001.SZ"

    @patch("time.sleep")
    @patch("sentinel.mgfs.data.tushare_kline_fetcher._import_tushare")
    def test_fetch_ohlcv_retries_on_failure(self, mock_import: Any, mock_sleep: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts

        mock_df = FakeDataFrame({
            "trade_date": ["20240101"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "vol": [5000],
        })
        mock_pro.daily.side_effect = [
            ConnectionError("timeout"),
            mock_df,
        ]

        fetcher = TushareKlineFetcher(token="fake_token", seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert len(bars) == 1
        assert mock_pro.daily.call_count == 2

    @patch("time.sleep")
    @patch("sentinel.mgfs.data.tushare_kline_fetcher._import_tushare")
    def test_fetch_ohlcv_raises_after_max_retries(self, mock_import: Any, mock_sleep: Any) -> None:
        mock_ts = MagicMock()
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_import.return_value = mock_ts
        mock_pro.daily.side_effect = ConnectionError("timeout")

        fetcher = TushareKlineFetcher(token="fake_token", seed=42)
        with pytest.raises(ConnectionError):
            fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert mock_pro.daily.call_count == 3

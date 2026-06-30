from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from sentinel.domain.models import Market
from sentinel.mgfs.data.eastmoney_kline_fetcher import EastmoneyKlineFetcher


class FakeResponse:
    def __init__(self, json_data: dict[str, Any] | None = None, status_code: int = 200, text: str = "") -> None:
        self._json = json_data or {}
        self.status_code = status_code
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")


class TestEastmoneyKlineFetcherInit:
    def test_init_sets_headers(self) -> None:
        fetcher = EastmoneyKlineFetcher(seed=42)
        assert "User-Agent" in fetcher._session.headers
        assert "Referer" in fetcher._session.headers


class TestEastmoneyKlineFetcherFetchOHLCV:
    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_returns_bars(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.return_value = FakeResponse(json_data={
            "rc": 0,
            "data": {
                "klines": [
                    "2024-01-02,1725.00,1730.50,1735.00,1718.00,12345,21345678.00,0.50,0.32,5.50,0.10",
                    "2024-01-03,1730.50,1728.00,1732.00,1725.00,9876,17000000.00,0.40,-0.14,-2.50,0.08",
                    "2024-01-04,1728.00,1735.00,1740.00,1726.00,15000,26000000.00,0.60,0.41,7.00,0.12",
                ]
            }
        })

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert len(bars) == 3
        assert bars[0].date == "2024-01-02"
        assert bars[0].open == 1725.0
        assert bars[0].close == 1730.5
        assert bars[0].high == 1735.0
        assert bars[0].low == 1718.0
        assert bars[0].volume == 12345

        # Verify URL contains correct market code and symbol
        call_url = mock_get.call_args[0][0]
        assert "secid=1.600519" in call_url

        # Verify random delay was called
        assert mock_sleep.called

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_shenzhen_symbol(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.return_value = FakeResponse(json_data={
            "rc": 0,
            "data": {
                "klines": [
                    "2024-01-02,10.0,10.5,11.0,9.8,50000,500000.00,1.20,5.00,0.50,0.50",
                ]
            }
        })

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("000001", Market.A_SHARE, days=120)

        assert len(bars) == 1
        call_url = mock_get.call_args[0][0]
        assert "secid=0.000001" in call_url

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_empty_returns_empty_list(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.return_value = FakeResponse(json_data={
            "rc": 0,
            "data": {"klines": []}
        })

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert bars == []

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_no_data_key_returns_empty_list(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.return_value = FakeResponse(json_data={"rc": 0})

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert bars == []

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_retries_on_network_error(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.side_effect = [
            requests.ConnectionError("Connection reset"),
            FakeResponse(json_data={
                "rc": 0,
                "data": {
                    "klines": [
                        "2024-01-02,100.0,101.0,102.0,99.0,10000,1000000.00,1.00,1.00,1.00,0.10",
                    ]
                }
            }),
        ]

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert len(bars) == 1
        assert mock_get.call_count == 2

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_retries_on_http_error(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.side_effect = [
            FakeResponse(status_code=503, text="Service Unavailable"),
            FakeResponse(json_data={
                "rc": 0,
                "data": {
                    "klines": [
                        "2024-01-02,100.0,101.0,102.0,99.0,10000,1000000.00,1.00,1.00,1.00,0.10",
                    ]
                }
            }),
        ]

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert len(bars) == 1
        assert mock_get.call_count == 2

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_raises_after_max_retries(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.side_effect = requests.ConnectionError("Connection reset")

        fetcher = EastmoneyKlineFetcher(seed=42)
        with pytest.raises(requests.ConnectionError):
            fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert mock_get.call_count == 3

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_can_fail_fast_for_ui_refresh(self, mock_get: Any, mock_sleep: Any) -> None:
        mock_get.side_effect = requests.ConnectionError("Connection reset")

        fetcher = EastmoneyKlineFetcher(
            seed=42,
            request_timeout=2.5,
            max_retries=1,
            delay_scale=0.0,
        )
        with pytest.raises(requests.ConnectionError):
            fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=120)

        assert mock_get.call_count == 1
        assert mock_get.call_args[1]["timeout"] == 2.5
        mock_sleep.assert_called_once_with(0.0)

    @patch("time.sleep")
    @patch("requests.Session.get")
    def test_fetch_ohlcv_limits_to_days(self, mock_get: Any, mock_sleep: Any) -> None:
        klines = [f"2024-01-{i:02d},100.0,101.0,102.0,99.0,10000,1000000.00,1.00,1.00,1.00,0.10" for i in range(1, 21)]
        mock_get.return_value = FakeResponse(json_data={
            "rc": 0,
            "data": {"klines": klines}
        })

        fetcher = EastmoneyKlineFetcher(seed=42)
        bars = fetcher.fetch_ohlcv("600519", Market.A_SHARE, days=10)

        assert len(bars) == 10

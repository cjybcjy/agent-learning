from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sentinel.domain.models import Market
from sentinel.mgfs.data.eastmoney_fetcher import EastmoneyValuationFetcher


class TestEastmoneyValuationFetcher:
    @pytest.fixture
    def fetcher(self, tmp_path: Path) -> EastmoneyValuationFetcher:
        return EastmoneyValuationFetcher(seed=42, cache_dir=tmp_path)

    def _mock_response(self, records: list[dict], total: int | None = None) -> MagicMock:
        """Build a mock urllib response."""
        total = total if total is not None else len(records)
        payload = {
            "result": {
                "data": records,
                "count": total,
                "pages": max(1, (total + 499) // 500),
            }
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("urllib.request.urlopen")
    def test_fetch_pe_ttm(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        records = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-01", "PE_TTM": 25.0},
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-02", "PE_TTM": 26.0},
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-03", "PE_TTM": 24.5},
        ]
        mock_urlopen.return_value = self._mock_response(records)

        history = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert len(history) == 3
        assert history == [25.0, 26.0, 24.5]
        mock_urlopen.assert_called()

    @patch("urllib.request.urlopen")
    def test_fetch_pb(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        records = [
            {"SECURITY_CODE": "000001", "TRADE_DATE": "2026-01-01", "PB_MRQ": 1.2},
            {"SECURITY_CODE": "000001", "TRADE_DATE": "2026-01-02", "PB_MRQ": 1.25},
        ]
        mock_urlopen.return_value = self._mock_response(records)

        history = fetcher.fetch_history("000001", Market.A_SHARE, "PB", years=1)

        assert len(history) == 2
        assert history == [1.2, 1.25]

    @patch("urllib.request.urlopen")
    def test_handles_none_values(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        records = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-01", "PE_TTM": None},
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-02", "PE_TTM": 20.0},
        ]
        mock_urlopen.return_value = self._mock_response(records)

        history = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert history == [-1.0, 20.0]

    @patch("urllib.request.urlopen")
    def test_pagination(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        # Simulate 600 records across 2 pages
        page1 = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": f"2026-01-{i:03d}", "PE_TTM": float(i)}
            for i in range(1, 501)
        ]
        page2 = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": f"2026-02-{i:03d}", "PE_TTM": float(i + 500)}
            for i in range(1, 101)
        ]

        def side_effect(*args, **kwargs):
            req = args[0]
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "pageNumber=1" in url:
                return self._mock_response(page1, total=600)
            if "pageNumber=2" in url:
                return self._mock_response(page2, total=600)
            return self._mock_response([])

        mock_urlopen.side_effect = side_effect

        history = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert len(history) == 600
        assert history[0] == 1.0
        assert history[-1] == 600.0
        assert mock_urlopen.call_count == 2

    @patch("urllib.request.urlopen")
    def test_retries_on_failure(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        mock_urlopen.side_effect = [
            Exception("Connection timeout"),
            Exception("Connection timeout"),
            self._mock_response([{"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-01", "PE_TTM": 20.0}]),
        ]

        history = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert len(history) == 1
        assert history[0] == 20.0
        assert mock_urlopen.call_count == 3

    @patch("urllib.request.urlopen")
    def test_raises_after_max_retries(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        mock_urlopen.side_effect = Exception("Persistent failure")

        with pytest.raises(Exception, match="Persistent failure"):
            fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert mock_urlopen.call_count == 3

    def test_invalid_metric_raises(self, fetcher: EastmoneyValuationFetcher) -> None:
        with pytest.raises(ValueError, match="not supported by Eastmoney API"):
            fetcher.fetch_history("600519", Market.A_SHARE, "INVALID_METRIC", years=1)

    @patch("urllib.request.urlopen")
    def test_uses_cache_on_second_call(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        records = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-01", "PE_TTM": 25.0},
        ]
        mock_urlopen.return_value = self._mock_response(records)

        # First call hits the API
        history1 = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)
        assert len(history1) == 1
        assert mock_urlopen.call_count == 1

        # Second call should use cache
        history2 = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)
        assert len(history2) == 1
        # No additional API calls
        assert mock_urlopen.call_count == 1

    @patch("urllib.request.urlopen")
    def test_user_agent_rotation(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        records = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-01-01", "PE_TTM": 20.0},
        ]
        mock_urlopen.return_value = self._mock_response(records)

        fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert mock_urlopen.called
        call_args = mock_urlopen.call_args
        assert call_args is not None
        req = call_args[0][0]
        headers = dict(req.header_items()) if hasattr(req, "header_items") else {}
        assert "User-Agent" in headers or "user-agent" in {k.lower(): v for k, v in headers.items()}

    @patch("urllib.request.urlopen")
    def test_filters_by_date(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        records = [
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2018-01-01", "PE_TTM": 30.0},
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-06-01", "PE_TTM": 25.0},
            {"SECURITY_CODE": "600519", "TRADE_DATE": "2026-06-02", "PE_TTM": 26.0},
        ]
        mock_urlopen.return_value = self._mock_response(records)

        history = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        # Should only include records from the last year
        assert len(history) == 2
        assert history == [25.0, 26.0]

    @patch("urllib.request.urlopen")
    def test_empty_response_returns_empty_list(self, mock_urlopen: MagicMock, fetcher: EastmoneyValuationFetcher) -> None:
        mock_urlopen.return_value = self._mock_response([])

        history = fetcher.fetch_history("600519", Market.A_SHARE, "PE_TTM", years=1)

        assert history == []

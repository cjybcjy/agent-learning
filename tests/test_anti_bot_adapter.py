from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from sentinel.mgfs.data.anti_bot_adapter import AntiBotAdapter


class TestUARotation:
    def test_ua_rotation_changes_between_requests(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        uas = [adapter._pick_ua() for _ in range(20)]
        unique_uas = set(uas)
        assert len(unique_uas) >= 5, f"Expected >=5 unique UAs, got {len(unique_uas)}"


class TestDelay:
    def test_delay_is_non_uniform(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        delays = [adapter._compute_delay(consecutive_success=i) for i in range(15)]
        long_pauses = [d for d in delays if d > 3.0]
        short_delays = [d for d in delays if d < 2.5]
        assert len(long_pauses) >= 1, f"Expected at least 1 long pause (>3.0s), got {long_pauses}"
        assert len(short_delays) >= 5, f"Expected >=5 short delays (<2.5s), got {short_delays}"

    def test_cold_start_delay_range(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        for _ in range(50):
            d = adapter._compute_delay(consecutive_success=0)
            assert 2.0 <= d <= 5.0

    def test_normal_delay_range(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        for i in range(1, 6):
            d = adapter._compute_delay(consecutive_success=i)
            assert 0.8 <= d <= 2.5

    def test_adaptive_acceleration_range(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        for _ in range(50):
            d = adapter._compute_delay(consecutive_success=12)
            assert 0.5 <= d <= 1.5

    def test_post_ban_delay_range(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        adapter._apply_ban(duration=60.0)
        for _ in range(50):
            d = adapter._compute_delay(consecutive_success=5)
            assert 2.0 <= d <= 8.0


class TestCurlCffiFallback:
    def test_curl_cffi_fallback_on_403(self) -> None:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            pytest.skip("curl_cffi not installed")

        adapter = AntiBotAdapter(use_curl_cffi=True, seed=42)
        assert adapter._curl_session is not None


class TestGetMethod:
    def test_get_success_increments_consecutive_success(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.raise_for_status.return_value = None

        with patch.object(adapter._session, "get", return_value=mock_resp) as mock_get:
            with patch("sentinel.mgfs.data.anti_bot_adapter.time.sleep"):
                resp = adapter.get("http://example.com")

        assert resp is mock_resp
        assert adapter._consecutive_success == 1
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert "headers" in call_kwargs
        assert "User-Agent" in call_kwargs["headers"]
        assert call_kwargs["timeout"] == 30

    def test_get_supports_fast_timeout_and_zero_delay(self) -> None:
        adapter = AntiBotAdapter(seed=42, request_timeout=2.5, delay_scale=0.0)
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.raise_for_status.return_value = None

        with patch.object(adapter._session, "get", return_value=mock_resp) as mock_get:
            with patch("sentinel.mgfs.data.anti_bot_adapter.time.sleep") as mock_sleep:
                adapter.get("http://example.com")

        assert adapter._compute_delay(consecutive_success=0) == 0.0
        mock_sleep.assert_called_once_with(0.0)
        assert mock_get.call_args[1]["timeout"] == 2.5

    def test_get_connection_error_resets_success(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        adapter._consecutive_success = 5

        with patch.object(adapter._session, "get", side_effect=requests.ConnectionError("boom")):
            with patch("sentinel.mgfs.data.anti_bot_adapter.time.sleep"):
                with pytest.raises(requests.ConnectionError):
                    adapter.get("http://example.com")

        assert adapter._consecutive_success == 0

    def test_get_403_triggers_ban_and_retries_with_curl(self) -> None:
        adapter = AntiBotAdapter(use_curl_cffi=True, seed=42)
        # If curl_cffi is not available, skip the retry portion
        if adapter._curl_session is None:
            pytest.skip("curl_cffi not installed")

        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=MagicMock(status_code=403))

        mock_curl_resp = MagicMock()
        mock_curl_resp.raise_for_status.return_value = None

        with patch.object(adapter._session, "get", return_value=mock_resp):
            with patch.object(adapter._curl_session, "get", return_value=mock_curl_resp) as mock_curl_get:
                with patch("sentinel.mgfs.data.anti_bot_adapter.time.sleep"):
                    resp = adapter.get("http://example.com")

        assert resp is mock_curl_resp
        assert adapter._consecutive_success == 1
        assert adapter._ban_until > time.time()
        mock_curl_get.assert_called_once()

    def test_get_429_triggers_ban(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.raise_for_status.side_effect = requests.HTTPError(response=MagicMock(status_code=429))

        with patch.object(adapter._session, "get", return_value=mock_resp):
            with patch("sentinel.mgfs.data.anti_bot_adapter.time.sleep"):
                with pytest.raises(requests.HTTPError):
                    adapter.get("http://example.com")

        assert adapter._consecutive_success == 0
        assert adapter._ban_until > time.time()


class TestBanState:
    def test_apply_ban_sets_ban_until_and_resets_success(self) -> None:
        adapter = AntiBotAdapter(seed=42)
        adapter._consecutive_success = 7
        before = time.time()
        adapter._apply_ban(duration=60.0)
        after = time.time()

        assert adapter._consecutive_success == 0
        assert before + 60.0 <= adapter._ban_until <= after + 60.0

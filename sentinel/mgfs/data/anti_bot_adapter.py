from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_UA_POOL = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on Android
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Firefox on Android
    "Mozilla/5.0 (Android 14; Mobile; rv:125.0) Gecko/125.0 Firefox/125.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Safari on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.2478.67",
    # Edge on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.2478.67",
    # Chrome on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.6367.71 Mobile/15E148 Safari/604.1",
    # Samsung Internet on Android
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/24.0 Chrome/117.0.0.0 Mobile Safari/537.36",
    # Chrome on iPad
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.6367.71 Mobile/15E148 Safari/604.1",
]


class AntiBotAdapter:
    def __init__(self, use_curl_cffi: bool = False, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self._session = requests.Session()
        self._curl_session: Any | None = None
        if use_curl_cffi:
            try:
                from curl_cffi import requests as curl_requests

                self._curl_session = curl_requests.Session()
            except ImportError:
                logger.warning("curl_cffi requested but not installed; falling back to requests")
        self._consecutive_success = 0
        self._ban_until = 0.0

    def _pick_ua(self) -> str:
        return self._rng.choice(_UA_POOL)

    def _compute_delay(self, consecutive_success: int = 0) -> float:
        now = time.time()
        if now < self._ban_until:
            return self._rng.uniform(2.0, 8.0)
        if consecutive_success == 0:
            return self._rng.uniform(2.0, 5.0)
        if consecutive_success >= 10:
            return self._rng.uniform(0.5, 1.5)
        if consecutive_success > 0 and consecutive_success % 7 == 0:
            return self._rng.uniform(5.0, 10.0)
        return self._rng.uniform(0.8, 2.5)

    def _apply_ban(self, duration: float = 60.0) -> None:
        self._ban_until = time.time() + duration
        self._consecutive_success = 0
        logger.warning("AntiBotAdapter banned for %.1f seconds", duration)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        headers = {
            "User-Agent": self._pick_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        delay = self._compute_delay(self._consecutive_success)
        time.sleep(delay)

        try:
            resp = self._session.get(url, headers=headers, timeout=30, **kwargs)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (403, 429):
                self._apply_ban()
                if self._curl_session is not None:
                    resp = self._curl_session.get(url, headers=headers, timeout=30, **kwargs)
                    resp.raise_for_status()
                    self._consecutive_success += 1
                    return resp
            raise
        except (requests.ConnectionError, requests.Timeout):
            self._consecutive_success = 0
            raise

        self._consecutive_success += 1
        return resp

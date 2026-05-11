import pytest
from heatmap.collectors.ua_pool import UserAgentPool

def test_ua_pool_returns_valid_ua():
    pool = UserAgentPool()
    ua = pool.random()
    assert isinstance(ua, str)
    assert len(ua) > 20
    assert any(browser in ua for browser in ["Chrome", "Firefox", "Safari"])

def test_ua_pool_returns_matching_headers():
    pool = UserAgentPool()
    headers = pool.random_headers()
    assert "User-Agent" in headers
    assert "Accept-Language" in headers

def test_ua_pool_randomizes():
    pool = UserAgentPool()
    uas = {pool.random() for _ in range(20)}
    assert len(uas) > 1

def test_ua_pool_custom_platform():
    pool = UserAgentPool(platforms=["macos"])
    for _ in range(20):
        ua = pool.random()
        assert "Macintosh" in ua or "Mac OS" in ua

import pytest
from heatmap.collectors.jitter import JitterManager, CookieJar, ReferrerChain

def test_jitter_delay_range():
    jm = JitterManager()
    for _ in range(50):
        delay = jm.compute_delay("example.com", 100.0)
        assert 70 <= delay <= 130

def test_cookie_jar_basic():
    jar = CookieJar()
    jar.save("example.com", {"session": "abc123"})
    assert jar.load("example.com") == {"session": "abc123"}

def test_cookie_jar_missing_domain():
    jar = CookieJar()
    assert jar.load("nonexistent.com") == {}

def test_cookie_jar_merge():
    jar = CookieJar()
    jar.save("example.com", {"a": "1"})
    jar.merge("example.com", {"b": "2"})
    assert jar.load("example.com") == {"a": "1", "b": "2"}

def test_referrer_chain_builds():
    chain = ReferrerChain()
    ref = chain.build("example.com/page")
    if ref is not None:
        assert ref.startswith("http")

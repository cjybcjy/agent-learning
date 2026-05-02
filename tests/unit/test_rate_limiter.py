import pytest
import asyncio
from heatmap.collectors.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit():
    limiter = RateLimiter({"xueqiu.com": 10.0})
    start = asyncio.get_event_loop().time()
    for _ in range(5):
        await limiter.acquire("xueqiu.com", "1.2.3.4")
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_rate_limiter_blocks_when_exceeded():
    limiter = RateLimiter({"xueqiu.com": 2.0})
    start = asyncio.get_event_loop().time()
    await limiter.acquire("xueqiu.com", "1.2.3.4")
    await limiter.acquire("xueqiu.com", "1.2.3.4")
    await limiter.acquire("xueqiu.com", "1.2.3.4")
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.4


@pytest.mark.asyncio
async def test_rate_limiter_fallback_without_proxy():
    limiter = RateLimiter({"xueqiu.com": 2.0})
    start = asyncio.get_event_loop().time()
    # Two calls without proxy should share the same domain bucket
    await limiter.acquire("xueqiu.com")  # no proxy
    await limiter.acquire("xueqiu.com")  # no proxy
    await limiter.acquire("xueqiu.com")  # should block, same bucket
    elapsed = asyncio.get_event_loop().time() - start
    assert elapsed >= 0.4  # waited for token refill


@pytest.mark.asyncio
async def test_rate_limiter_concurrent_acquires():
    limiter = RateLimiter({"xueqiu.com": 10.0})

    async def acquire_many():
        for _ in range(3):
            await limiter.acquire("xueqiu.com", "1.2.3.4")

    await asyncio.gather(acquire_many(), acquire_many())
    # Should complete without errors - lock prevents race conditions

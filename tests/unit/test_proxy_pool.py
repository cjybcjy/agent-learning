import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from heatmap.collectors.proxy_pool import ProxyPool


@pytest.mark.asyncio
async def test_proxy_pool_returns_available_proxy():
    pool = ProxyPool(["http://p1:8080", "http://p2:8080"])
    proxy = await pool.get()
    assert proxy in ["http://p1:8080", "http://p2:8080"]


@pytest.mark.asyncio
async def test_proxy_pool_cools_down_after_failures():
    pool = ProxyPool(["http://p1:8080"], cooldown_seconds=1.0)
    await pool.report_failure("http://p1:8080")
    await pool.report_failure("http://p1:8080")
    await pool.report_failure("http://p1:8080")
    proxy = await pool.get()
    assert proxy is None


@pytest.mark.asyncio
async def test_proxy_pool_recovers_after_cooldown():
    pool = ProxyPool(["http://p1:8080"], cooldown_seconds=0.5, reaper_interval=0.1)
    await pool.start()
    await pool.report_failure("http://p1:8080")
    await pool.report_failure("http://p1:8080")
    await pool.report_failure("http://p1:8080")
    assert await pool.get() is None
    await asyncio.sleep(1.0)  # wait for reaper
    proxy = await pool.get()
    assert proxy == "http://p1:8080"
    await pool.stop()

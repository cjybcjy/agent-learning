import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from heatmap.collectors.xueqiu import XueqiuCollector
from heatmap.extractor.ac import AhoCorasickExtractor
from heatmap.extractor.dictionary import AliasEntry


@pytest.mark.asyncio
async def test_xueqiu_collector_fetches_and_queues_posts():
    queue = asyncio.Queue()
    extractor = AhoCorasickExtractor([
        AliasEntry("BTC", "BTC", False, "seed"),
    ])
    collector = XueqiuCollector(extractor, queue, market="a_share", poll_interval=0.1)

    mock_resp = MagicMock()
    mock_resp.headers.get.return_value = "application/json"
    mock_resp.json.return_value = {
        "list": [
            {
                "description": "BTC is going to the moon",
                "symbol": "BTC",
                "user_id": 12345,
                "created_at": 1714147200000,
            }
        ]
    }

    with patch.object(collector, "_request", return_value=mock_resp):
        await collector._poll_once()

    assert queue.qsize() == 1
    qm = queue.get_nowait()
    assert qm.raw.platform == "xueqiu"
    assert qm.raw.market == "a_share"
    assert "BTC" in qm.raw.content
    assert len(qm.mentions or []) == 1
    assert qm.mentions[0].symbol == "BTC"

    await collector.close()


@pytest.mark.asyncio
async def test_xueqiu_collector_handles_empty_response():
    queue = asyncio.Queue()
    extractor = AhoCorasickExtractor([])
    collector = XueqiuCollector(extractor, queue, market="a_share", poll_interval=0.1)

    mock_resp = MagicMock()
    mock_resp.headers.get.return_value = "application/json"
    mock_resp.json.return_value = {"list": []}

    with patch.object(collector, "_request", return_value=mock_resp):
        await collector._poll_once()

    assert queue.qsize() == 0
    await collector.close()


@pytest.mark.asyncio
async def test_xueqiu_collector_handles_error():
    queue = asyncio.Queue()
    extractor = AhoCorasickExtractor([])
    collector = XueqiuCollector(extractor, queue, market="a_share", poll_interval=0.1)

    with patch.object(collector, "_request", side_effect=Exception("network error")):
        await collector._poll_once()

    assert queue.qsize() == 0
    await collector.close()


@pytest.mark.asyncio
async def test_xueqiu_collector_skips_on_waf_block():
    """When Xueqiu returns non-JSON (WAF), skip poll — never fallback to synthetic data."""
    queue = asyncio.Queue()
    extractor = AhoCorasickExtractor([
        AliasEntry("茅台", "茅台", False, "seed"),
    ])
    collector = XueqiuCollector(extractor, queue, market="a_share", poll_interval=0.1)

    home_resp = MagicMock()
    waf_resp = MagicMock()
    waf_resp.headers.get.return_value = "text/html"

    with patch.object(collector, "_request", side_effect=[home_resp, waf_resp]):
        await collector._poll_once()

    assert queue.qsize() == 0
    await collector.close()


@pytest.mark.asyncio
async def test_xueqiu_collector_skips_on_exception():
    """When Xueqiu request raises exception, skip poll — no fallback."""
    queue = asyncio.Queue()
    extractor = AhoCorasickExtractor([
        AliasEntry("平安银行", "平安银行", False, "seed"),
    ])
    collector = XueqiuCollector(extractor, queue, market="a_share", poll_interval=0.1)

    with patch.object(collector, "_request", side_effect=Exception("timeout")):
        await collector._poll_once()

    assert queue.qsize() == 0
    await collector.close()

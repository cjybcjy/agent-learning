import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

from heatmap.collectors.eastmoney import EastmoneyCollector, _generate_content, _pick_sentiment


@pytest.mark.asyncio
async def test_eastmoney_fetch_posts_parses_diff():
    collector = EastmoneyCollector(None, None, market="a_share")

    mock_resp = AsyncMock()
    # httpx.Response.json() is synchronous
    mock_resp.json = Mock(return_value={
        "data": {
            "diff": [
                {"f12": "600519", "f14": "贵州茅台", "f3": 5.2},
                {"f12": "300750", "f14": "宁德时代", "f3": -2.1},
                {"f12": "000858", "f14": "五粮液", "f3": 10.0},
            ]
        }
    })
    collector._request = AsyncMock(return_value=mock_resp)

    posts = await collector._fetch_posts()

    assert len(posts) == 3
    assert all(p["platform"] == "eastmoney" for p in posts)
    assert all(p["channel"] == "hot_rank" for p in posts)
    assert all(p["author_id"] == "eastmoney_bot" for p in posts)
    assert all(isinstance(p["posted_at"], datetime) for p in posts)

    # Check content includes stock names
    contents = [p["content"] for p in posts]
    assert any("茅台" in c for c in contents)
    assert any("宁德时代" in c for c in contents)


@pytest.mark.asyncio
async def test_eastmoney_handles_empty_diff():
    collector = EastmoneyCollector(None, None, market="a_share")

    mock_resp = AsyncMock()
    mock_resp.json = Mock(return_value={"data": {"diff": []}})
    collector._request = AsyncMock(return_value=mock_resp)

    posts = await collector._fetch_posts()
    assert posts == []


@pytest.mark.asyncio
async def test_eastmoney_handles_missing_data():
    collector = EastmoneyCollector(None, None, market="a_share")

    mock_resp = AsyncMock()
    mock_resp.json = Mock(return_value={"data": None})
    collector._request = AsyncMock(return_value=mock_resp)

    posts = await collector._fetch_posts()
    assert posts == []


@pytest.mark.asyncio
async def test_eastmoney_graceful_on_exception():
    collector = EastmoneyCollector(None, None, market="a_share")
    collector._request = AsyncMock(side_effect=Exception("network error"))

    posts = await collector._fetch_posts()
    assert posts == []


def test_pick_sentiment():
    assert _pick_sentiment(9.5) == "strong_up"
    assert _pick_sentiment(5.0) == "up"
    assert _pick_sentiment(0.1) == "up"
    assert _pick_sentiment(0.0) == "flat"
    assert _pick_sentiment(-1.0) == "flat"
    assert _pick_sentiment(-3.1) == "down"
    assert _pick_sentiment(-5.0) == "down"


def test_generate_content_includes_name():
    content = _generate_content("贵州茅台", 5.0)
    assert "茅台" in content
    assert len(content) > 5

    content = _generate_content("宁德时代", -4.0)
    assert "宁德时代" in content

    content = _generate_content("比亚迪", 0.0)
    assert "比亚迪" in content

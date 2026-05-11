import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from heatmap.collectors.jqka import JqkaCollector


@pytest.mark.asyncio
async def test_jqka_fetch_posts_structure():
    collector = JqkaCollector(extractor=MagicMock(), queue=MagicMock(), market="a_share")
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value.text = '<a href="/stock/000001/">平安银行</a><a href="/stock/600519/">贵州茅台</a>'
        posts = await collector._fetch_posts()
        assert len(posts) >= 1
        assert all("content" in p for p in posts)
        assert all(p["platform"] == "jqka" for p in posts)


@pytest.mark.asyncio
async def test_jqka_empty_response():
    collector = JqkaCollector(extractor=MagicMock(), queue=MagicMock(), market="a_share")
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value.text = ''
        posts = await collector._fetch_posts()
        assert posts == []

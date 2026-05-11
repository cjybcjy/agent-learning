import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
from heatmap.collectors.cls import ClsCollector


@pytest.mark.asyncio
async def test_cls_fetch_posts_structure():
    collector = ClsCollector(extractor=MagicMock(), queue=MagicMock(), market="a_share")

    mock_resp = AsyncMock()
    mock_resp.json = Mock(return_value={
        "data": {"roll_data": [{"title": "测试新闻", "content": "测试内容"}]}
    })
    collector._request = AsyncMock(return_value=mock_resp)

    posts = await collector._fetch_posts()
    assert len(posts) == 1
    assert posts[0]["platform"] == "cls"

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from heatmap.collectors.aastocks import AastocksCollector


@pytest.mark.asyncio
async def test_aastocks_fetch_posts():
    collector = AastocksCollector(extractor=MagicMock(), queue=MagicMock(), market="hk")
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value.text = 'stock 00700 Tencent stock 09988 Alibaba'
        posts = await collector._fetch_posts()
        assert len(posts) >= 1
        assert all(p["platform"] == "aastocks" for p in posts)

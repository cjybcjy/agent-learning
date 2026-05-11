import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from heatmap.collectors.coingecko import CoingeckoCollector

@pytest.mark.asyncio
async def test_coingecko_fetch_posts():
    collector = CoingeckoCollector(extractor=MagicMock(), queue=MagicMock(), market="crypto")
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_req.return_value.json = MagicMock(return_value={"coins": [{"item": {"name": "Bitcoin", "symbol": "btc", "market_cap_rank": 1, "score": 100}}]})
        posts = await collector._fetch_posts()
        assert len(posts) == 1
        assert posts[0]["platform"] == "coingecko"
        assert "Bitcoin" in posts[0]["content"]

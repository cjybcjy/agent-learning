import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from heatmap.collectors.reddit import RedditCollector


@pytest.mark.asyncio
async def test_reddit_filters_noise():
    collector = RedditCollector(extractor=MagicMock(), queue=MagicMock(), market="us")
    with patch.object(collector, '_request', new_callable=AsyncMock) as mock_req:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"children": [
                {"data": {
                    "title": "YOLO play of the day",
                    "selftext": "loss porn incoming",
                    "score": 100,
                    "upvote_ratio": 0.9,
                    "link_flair_text": None,
                    "author": "user1",
                }},
                {"data": {
                    "title": "DD: Deep analysis of GME",
                    "selftext": "Here is why...",
                    "score": 50,
                    "upvote_ratio": 0.85,
                    "link_flair_text": "DD",
                    "author": "user2",
                }},
            ]},
        }
        mock_req.return_value = mock_resp
        posts = await collector._fetch_posts()
        assert len(posts) == 1  # Only DD post survives filter
        assert "DD" in posts[0]["content"]

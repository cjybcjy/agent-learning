import pytest
from fastapi.testclient import TestClient

import heatmap.web.api
from heatmap.web.api import app
from heatmap.store.dao import RawMessage, Mention


def _seed_test_data():
    """Insert test data into the app's database. Must be called after TestClient enters."""
    import asyncio

    async def _do():
        from datetime import datetime, timezone

        store = heatmap.web.api.store
        assert store is not None, "Store not initialized — call this inside TestClient context"

        # Insert crypto messages (window 2026-05-01T14:00:00Z)
        for i in range(3):
            msg = RawMessage(
                platform="telegram", channel="@crypto1",
                author_id="u1", content=f"BTC to the moon {i}",
                posted_at=datetime(2026, 5, 1, 14, 5, 0, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 1, 14, 5, 0, tzinfo=timezone.utc),
                market="crypto",
            )
            mid = await store.insert_message(msg)
            await store.insert_mentions([
                Mention(mid, "BTC", "BTC", False, 1.0),
            ])

        # Insert a_share messages (same window)
        for i in range(2):
            msg = RawMessage(
                platform="xueqiu", channel="hot",
                author_id="u2", content=f"茅台突破 2000 {i}",
                posted_at=datetime(2026, 5, 1, 14, 10, 0, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 5, 1, 14, 10, 0, tzinfo=timezone.utc),
                market="a_share",
            )
            mid = await store.insert_message(msg)
            await store.insert_mentions([
                Mention(mid, "茅台", "茅台", False, 1.0),
            ])

        # Insert rollup data directly
        await store.insert_rollup_30min("BTC", "2026-05-01T14:00:00Z", "crypto", 3, 3.0, 1)
        await store.insert_rollup_30min("ETH", "2026-05-01T14:00:00Z", "crypto", 1, 1.0, 1)
        await store.insert_rollup_30min("茅台", "2026-05-01T14:00:00Z", "a_share", 2, 2.0, 1)

    asyncio.run(_do())


class TestHeatmapAPI:
    """REST API market filtering smoke tests."""

    def test_heatmap_filter_by_crypto(self):
        with TestClient(app) as client:
            _seed_test_data()
            resp = client.get("/api/heatmap?granularity=30min&market=crypto&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            symbols = [item["symbol"] for item in data["items"]]
            assert "BTC" in symbols
            assert "ETH" in symbols
            assert "茅台" not in symbols

    def test_heatmap_filter_by_a_share(self):
        with TestClient(app) as client:
            _seed_test_data()
            resp = client.get("/api/heatmap?granularity=30min&market=a_share&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            symbols = [item["symbol"] for item in data["items"]]
            assert "茅台" in symbols
            assert "BTC" not in symbols
            assert "ETH" not in symbols

    def test_heatmap_all_markets(self):
        with TestClient(app) as client:
            _seed_test_data()
            resp = client.get("/api/heatmap?granularity=30min&market=all&limit=10")
            assert resp.status_code == 200
            data = resp.json()
            symbols = [item["symbol"] for item in data["items"]]
            assert "BTC" in symbols
            assert "ETH" in symbols
            assert "茅台" in symbols

    def test_symbols_filter_by_market(self):
        with TestClient(app) as client:
            _seed_test_data()
            resp = client.get("/api/symbols?market=crypto")
            assert resp.status_code == 200
            data = resp.json()
            assert "BTC" in data["symbols"]
            assert "ETH" in data["symbols"]
            assert "茅台" not in data["symbols"]

    def test_symbols_a_share(self):
        with TestClient(app) as client:
            _seed_test_data()
            resp = client.get("/api/symbols?market=a_share")
            assert resp.status_code == 200
            data = resp.json()
            assert "茅台" in data["symbols"]
            assert "BTC" not in data["symbols"]

    def test_trend_returns_data(self):
        with TestClient(app) as client:
            _seed_test_data()
            resp = client.get("/api/heatmap/BTC/trend?granularity=30min")
            assert resp.status_code == 200
            data = resp.json()
            assert data["symbol"] == "BTC"
            assert len(data["data"]) == 1
            assert data["data"][0]["mention_count"] == 3


class TestWebSocketSmoke:
    """WebSocket end-to-end smoke tests."""

    def test_ws_subscribe_and_receive(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/heatmap") as ws:
                ws.send_json({"action": "subscribe", "markets": ["crypto"]})
                msg = ws.receive_json()
                assert msg["type"] == "subscribed"
                assert "crypto" in msg["markets"]

    def test_ws_ping_pong(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/heatmap") as ws:
                ws.send_json({"type": "ping", "timestamp": 42})
                msg = ws.receive_json()
                assert msg["type"] == "pong"
                assert msg["timestamp"] == 42

    def test_ws_invalid_json(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/heatmap") as ws:
                ws.send_text("broken json {{{")
                msg = ws.receive_json()
                assert msg["type"] == "error"

    def test_ws_unsubscribe(self):
        with TestClient(app) as client:
            with client.websocket_connect("/ws/heatmap") as ws:
                ws.send_json({"action": "subscribe", "markets": ["crypto", "a_share"]})
                ws.receive_json()  # subscribed

                ws.send_json({"action": "unsubscribe", "markets": ["a_share"]})
                msg = ws.receive_json()
                assert msg["type"] == "unsubscribed"
                assert "a_share" in msg["markets"]

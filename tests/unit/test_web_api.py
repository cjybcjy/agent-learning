import pytest
from fastapi.testclient import TestClient
from heatmap.web.api import app

client = TestClient(app)


def test_api_heatmap_returns_data():
    response = client.get("/api/heatmap?granularity=30min&market=crypto&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "next_cursor" in data


def test_api_heatmap_enforces_max_limit():
    response = client.get("/api/heatmap?limit=500")
    assert response.status_code == 422


def test_api_markets():
    response = client.get("/api/markets")
    assert response.status_code == 200
    assert "a_share" in response.json()["markets"]


def test_api_chat_sse():
    response = client.post("/api/chat", json={"question": "test"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

import pytest
from fastapi.testclient import TestClient
from heatmap.web.api import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_heatmap_returns_data(client):
    response = client.get("/api/heatmap?granularity=30min&market=crypto&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "next_cursor" in data


def test_api_heatmap_enforces_max_limit(client):
    response = client.get("/api/heatmap?limit=500")
    assert response.status_code == 422


def test_api_markets(client):
    response = client.get("/api/markets")
    assert response.status_code == 200
    assert "a_share" in response.json()["markets"]


def test_api_chat_sse(client):
    response = client.post("/api/chat", json={"question": "test"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


class TestModelManagementAPI:
    """Tests for /api/models, /api/models/current, /api/models/switch."""

    def test_get_models_returns_providers(self, client):
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) == 5
        provider_names = {p["provider"] for p in data["providers"]}
        assert "deepseek" in provider_names
        assert "kimi" in provider_names
        assert "bailian" in provider_names

    def test_get_models_provider_structure(self, client):
        response = client.get("/api/models")
        data = response.json()
        deepseek = next(p for p in data["providers"] if p["provider"] == "deepseek")
        assert deepseek["display_name"] == "DeepSeek"
        assert deepseek["default_model"] == "deepseek-chat"
        assert deepseek["api_key_env"] == "DEEPSEEK_API_KEY"

    def test_get_current_model_returns_valid_provider(self, client):
        response = client.get("/api/models/current")
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] in {"deepseek", "kimi", "bailian", "claude", "openai"}
        assert "model" in data
        assert "display_name" in data

    def test_switch_model_changes_provider(self, client):
        response = client.post("/api/models/switch", json={
            "provider": "kimi",
            "model": "moonshot-v1-32k",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["provider"] == "kimi"
        assert data["model"] == "moonshot-v1-32k"

        # Verify current reflects the change
        response = client.get("/api/models/current")
        assert response.json()["provider"] == "kimi"
        assert response.json()["model"] == "moonshot-v1-32k"

    def test_switch_model_without_model_uses_default(self, client):
        response = client.post("/api/models/switch", json={
            "provider": "openai",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-4o"

    def test_switch_unknown_provider_returns_400(self, client):
        response = client.post("/api/models/switch", json={
            "provider": "nonexistent",
        })
        assert response.status_code == 400
        assert "error" in response.json()

    def test_config_includes_provider_status(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert "deepseek" in data["providers"]
        status = data["providers"]["deepseek"]
        assert "configured" in status
        assert "source" in status
        assert "api_key_env" in status

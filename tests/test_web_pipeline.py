from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_pipeline_trigger_returns_started():
    client = TestClient(create_app())
    response = client.post("/api/pipeline/trigger")
    assert response.status_code == 200
    assert response.json()["status"] == "started"


def test_pipeline_history_returns_table():
    client = TestClient(create_app())
    response = client.get("/api/pipeline/history")
    assert response.status_code == 200
    assert "大盘巡检" in response.text

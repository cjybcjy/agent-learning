from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_scan_start_returns_task_id():
    client = TestClient(create_app())
    response = client.post("/api/scan/start", data={"theme": "Consumer_Staples"})
    assert response.status_code == 200
    assert "scan-task-id" in response.text

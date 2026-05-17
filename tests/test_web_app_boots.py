from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_app_creates_without_error():
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

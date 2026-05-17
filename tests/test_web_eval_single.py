from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_eval_single_returns_decision_card():
    client = TestClient(create_app())
    response = client.post("/api/eval/single", data={"symbol": "600519", "market": "A_SHARE"})
    assert response.status_code == 200
    assert "600519" in response.text
    assert "护城河" in response.text

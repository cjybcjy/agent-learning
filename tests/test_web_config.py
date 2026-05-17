from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_config_load_returns_editor():
    client = TestClient(create_app())
    response = client.get("/api/config/load/ecosystem_themes.yaml")
    assert response.status_code == 200
    assert "ecosystem_themes.yaml" in response.text


def test_config_validate_detects_yaml_error():
    client = TestClient(create_app())
    response = client.post("/api/config/validate", data={"content": "invalid: ["})
    assert response.status_code == 200
    assert "YAML 语法错误" in response.text

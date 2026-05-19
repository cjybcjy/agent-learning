from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_pipeline_trigger_returns_started():
    with patch("sentinel.web.routers.ops._get_pipeline_service") as mock_svc:
        mock_instance = MagicMock()
        mock_instance.create_batch.return_value = "B_20260518_120000"
        mock_instance.get_history.return_value = []
        mock_svc.return_value = mock_instance

        client = TestClient(create_app())
        response = client.post("/api/pipeline/trigger")
        assert response.status_code == 200
        assert "B_20260518_120000" in response.text
        mock_instance.create_batch.assert_called_once()


def test_pipeline_history_returns_table():
    with patch("sentinel.web.routers.ops._get_pipeline_service") as mock_svc:
        mock_instance = MagicMock()
        mock_instance.get_history.return_value = []
        mock_svc.return_value = mock_instance

        client = TestClient(create_app())
        response = client.get("/api/pipeline/history")
        assert response.status_code == 200
        assert "大盘巡检" in response.text

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.config import AppSettings
from sentinel.web.main import create_app


def _prepare_calibration_env(
    tmp_path: Path,
    monkeypatch,
    symbols: tuple[str, ...] = ("300750", "600519"),
) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / ".cache" / "sentinel" / "eastmoney"
    config_dir.mkdir()
    data_dir.mkdir()
    cache_dir.mkdir(parents=True)
    (config_dir / "moat_static_base.yaml").write_text(
        """
companies:
  "300750":
    name: "宁德时代"
    base_score: 84.0
  "600519":
    name: "贵州茅台"
    base_score: 80.6
""",
        encoding="utf-8",
    )

    import json

    start = date(2025, 1, 1)
    rows = [
        {
            "TRADE_DATE": str(start + timedelta(days=i)),
            "CLOSE_PRICE": str(100 + i),
        }
        for i in range(35)
    ]
    for symbol in symbols:
        (cache_dir / f"{symbol}_all_20250101.json").write_text(
            json.dumps(rows),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "sentinel.config.AppSettings",
        lambda: AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir),
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def test_calibration_page_shows_report_table(tmp_path, monkeypatch):
    """Calibration endpoint should return HTML table with bias penalties."""
    _prepare_calibration_env(tmp_path, monkeypatch)
    with patch("sentinel.web.routers.ops._run_backtest") as mock_run:
        from sentinel.mgfs.evolution.bayes_calibrator import CalibrationReport

        mock_run.return_value = [
            CalibrationReport(
                symbol="300750",
                name="宁德时代",
                static_score=84.0,
                bias_penalty=-17.09,
                suggested_score=66.9,
                confidence=0.46,
                reason="1次止损; 总收益-2.5%",
            ),
            CalibrationReport(
                symbol="600519",
                name="贵州茅台",
                static_score=80.6,
                bias_penalty=-1.85,
                suggested_score=78.7,
                confidence=0.46,
                reason="总收益-5.3%",
            ),
        ]

        client = TestClient(create_app())
        response = client.get("/api/calibration/reports")
        assert response.status_code == 200
        html = response.text
        assert "300750" in html
        assert "宁德时代" in html
        assert "-17.09" in html
        assert "600519" in html
        assert "贵州茅台" in html


def test_calibration_page_shows_empty_state(tmp_path, monkeypatch):
    """No reports → show empty message."""
    _prepare_calibration_env(tmp_path, monkeypatch, symbols=())
    with patch("sentinel.web.routers.ops._run_backtest") as mock_run:
        mock_run.return_value = []

        client = TestClient(create_app())
        response = client.get("/api/calibration/reports")
        assert response.status_code == 200
        assert "暂无校准数据" in response.text


def test_calibration_report_uses_stock_name_code_format(tmp_path, monkeypatch):
    """Calibration labels should render as stock name(code), not code(code)."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text(
        """
companies:
  "300750":
    name: "宁德时代"
    base_score: 84.0
""",
        encoding="utf-8",
    )

    cache_dir = tmp_path / ".cache" / "sentinel" / "eastmoney"
    cache_dir.mkdir(parents=True)
    start = date(2025, 1, 1)
    rows = [
        {
            "TRADE_DATE": str(start + timedelta(days=i)),
            "CLOSE_PRICE": str(100 + i),
        }
        for i in range(35)
    ]
    import json

    (cache_dir / "300750_all_20250101.json").write_text(
        json.dumps(rows),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sentinel.config.AppSettings",
        lambda: AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir),
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    client = TestClient(create_app())
    response = client.get(
        "/api/calibration/reports",
        params={
            "symbols": "300750",
            "start_date": "2025-01-01",
            "end_date": "2025-02-28",
        },
    )

    assert response.status_code == 200
    assert "宁德时代（300750）" in response.text
    assert "300750（300750）" not in response.text


def test_calibration_report_shows_research_validation_status(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text(
        """
companies:
  "300750":
    name: "宁德时代"
    base_score: 86.0
""",
        encoding="utf-8",
    )

    cache_dir = tmp_path / ".cache" / "sentinel" / "eastmoney"
    cache_dir.mkdir(parents=True)
    start = date(2025, 1, 1)
    rows = [
        {
            "TRADE_DATE": str(start + timedelta(days=i)),
            "CLOSE_PRICE": str(100 + i),
        }
        for i in range(35)
    ]
    import json

    (cache_dir / "300750_all_20250101.json").write_text(
        json.dumps(rows),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sentinel.config.AppSettings",
        lambda: AppSettings(base_dir=tmp_path, config_dir=config_dir, data_dir=data_dir),
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    client = TestClient(create_app())
    response = client.get(
        "/api/calibration/reports",
        params={
            "symbols": "300750",
            "start_date": "2025-01-01",
            "end_date": "2025-02-28",
        },
    )

    assert response.status_code == 200
    assert "研究可信度" in response.text
    assert "校验通过" in response.text
    assert "decision_inputs.jsonl" in response.text
    assert "mgfs_research_signal_v1.jsonl" in response.text

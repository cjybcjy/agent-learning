from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_scan_result_includes_scatter_chart():
    """Scan result page should include ecosystem scatter chart container."""
    with patch("sentinel.web.routers.research.get_task") as mock_get_task:
        task = MagicMock()
        task.status.value = "completed"

        report = MagicMock()
        report.target.symbol = "600519"
        report.target.name = "贵州茅台"
        report.target.ecosystem_role = "downstream_app"
        report.final_score = 85.0
        report.rating = "Strong Buy"
        report.action = "重仓"
        report.factor_scores = {
            "moat": MagicMock(score=80.0),
            "valuation": MagicMock(details={"primary_percentile": 15.0, "zone": "strong_buy"}),
        }

        task.reports = [report]
        task.summary = {}
        mock_get_task.return_value = task

        client = TestClient(create_app())
        response = client.get("/api/scan/result/test123")
        assert response.status_code == 200
        html = response.text
        assert "ecosystem-scatter-chart" in html
        assert "data-scatter-data" in html


def test_scan_matrix_serializes_report_data():
    """Scan matrix template should serialize report data for ECharts."""
    from sentinel.web.services.scan_service import ScanTask, ScanTaskStatus
    from jinja2 import Environment, BaseLoader

    # Build a minimal template render test
    template_str = """
    {% set scatter_data = [] %}
    {% for r in reports %}
    {% set moat = r.factor_scores.get("moat") %}
    {% set val = r.factor_scores.get("valuation") %}
    {% set _ = scatter_data.append({
        "symbol": r.target.symbol,
        "name": r.target.name or r.target.symbol,
        "moat": moat.score if moat else 0,
        "percentile": val.details.get("primary_percentile", 50) if val and val.details else 50,
        "score": r.final_score,
        "role": r.target.ecosystem_role or "unknown"
    }) %}
    {% endfor %}
    {{ scatter_data | tojson }}
    """

    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)

    report = MagicMock()
    report.target.symbol = "600519"
    report.target.name = "贵州茅台"
    report.target.ecosystem_role = "downstream_app"
    report.final_score = 85.0

    moat = MagicMock()
    moat.score = 80.0
    report.factor_scores = {"moat": moat}

    val = MagicMock()
    val.details = {"primary_percentile": 15.0}
    report.factor_scores["valuation"] = val

    result = template.render(reports=[report])
    import json
    data = json.loads(result.strip())
    assert len(data) == 1
    assert data[0]["symbol"] == "600519"
    assert data[0]["moat"] == 80.0
    assert data[0]["percentile"] == 15.0
    assert data[0]["score"] == 85.0
    assert data[0]["role"] == "downstream_app"

from fastapi.testclient import TestClient

import sentinel.web.routers.ops as ops_router
from sentinel.web import dependencies
from sentinel.web.main import create_app
from sentinel.web.services.config_change_service import ConfigChangeProposal
from sentinel.web.services.pipeline_service import PipelineService


def test_config_load_returns_editor():
    client = TestClient(create_app())
    response = client.get("/api/config/load/ecosystem_themes.yaml")
    assert response.status_code == 200
    assert "ecosystem_themes.yaml" in response.text


def test_config_load_allows_mgfs_config():
    client = TestClient(create_app())
    response = client.get("/api/config/load/mgfs_config.yaml")
    assert response.status_code == 200
    assert "mgfs_config.yaml" in response.text


def test_config_load_allows_research_signal_sources():
    client = TestClient(create_app())
    response = client.get("/api/config/load/research_signal_sources.yaml")
    assert response.status_code == 200
    assert "research_signal_sources.yaml" in response.text


def test_config_validate_detects_yaml_error():
    client = TestClient(create_app())
    response = client.post("/api/config/validate", data={"content": "invalid: ["})
    assert response.status_code == 200
    assert "YAML 语法错误" in response.text


def test_config_validate_mgfs_config_reports_schema_paths():
    client = TestClient(create_app())
    response = client.post(
        "/api/config/validate",
        data={
            "filename": "mgfs_config.yaml",
            "content": "modules: {}\nscoring_formula:\n  moat:\n    weight: -0.2\n",
        },
    )
    assert response.status_code == 200
    assert "校验失败" in response.text
    assert "scoring_formula.moat.weight" in response.text


def test_config_save_mgfs_config_rejects_schema_errors():
    client = TestClient(create_app())
    response = client.post(
        "/api/config/save",
        data={
            "filename": "mgfs_config.yaml",
            "content": "modules: {}\nscoring_formula:\n  moat:\n    weight: -0.2\n",
        },
    )
    assert response.status_code == 200
    assert "校验失败" in response.text
    assert "scoring_formula.moat.weight" in response.text


def test_config_save_success_resets_runtime_services(monkeypatch):
    called = {"reset": False}
    monkeypatch.setattr(ops_router, "save_config", lambda filename, content: (True, "配置已保存"))
    monkeypatch.setattr(
        ops_router,
        "_reset_runtime_services",
        lambda: called.__setitem__("reset", True),
    )

    response = TestClient(create_app()).post(
        "/api/config/save",
        data={"filename": "policy_whitelist.yaml", "content": "version: '1.0'\n"},
    )

    assert response.status_code == 200
    assert called["reset"] is True


def test_score_composition_save_uses_structured_fields(monkeypatch):
    captured = {}
    called = {"reset": False}

    def fake_save_score_composition(**kwargs):
        captured.update(kwargs)
        return True, "总分构成配置已保存"

    monkeypatch.setattr(
        ops_router,
        "save_score_composition",
        fake_save_score_composition,
        raising=False,
    )
    monkeypatch.setattr(
        ops_router,
        "_reset_runtime_services",
        lambda: called.__setitem__("reset", True),
    )

    response = TestClient(create_app()).post(
        "/api/config/score-composition",
        data={
            "moat_weight": "0.45",
            "valuation_weight": "0.25",
            "policy_weight": "0.1",
            "timing_weight": "0.2",
            "strong_buy_min_score": "88",
            "accumulate_min_score": "74",
            "hold_watch_min_score": "58",
        },
    )

    assert response.status_code == 200
    assert "总分构成配置已保存" in response.text
    assert captured == {
        "moat_weight": 0.45,
        "valuation_weight": 0.25,
        "policy_weight": 0.1,
        "timing_weight": 0.2,
        "strong_buy_min_score": 88.0,
        "accumulate_min_score": 74.0,
        "hold_watch_min_score": 58.0,
    }
    assert called["reset"] is True


def test_reset_runtime_services_clears_cached_dependencies():
    dependencies._orchestrator = object()
    dependencies._scanner = object()
    ops_router._pipeline_svc = PipelineService(orchestrator=object())  # type: ignore[arg-type]

    ops_router._reset_runtime_services()

    assert dependencies._orchestrator is None
    assert dependencies._scanner is None
    assert ops_router._pipeline_svc is None


class FakeConfigChangeService:
    def __init__(self) -> None:
        self.proposal = ConfigChangeProposal(
            id="abc123",
            action="add",
            title="添加估值路由: 家电",
            config_file="valuation_sector_routing.yaml",
            path="sector_to_archetype.家电",
            current_value=None,
            proposed_value="traditional_growth",
            rationale="股票池中存在家电，但估值路由未显式配置。",
        )

    def scan_proposals(self) -> list[ConfigChangeProposal]:
        return [self.proposal]

    def approve_proposal(self, proposal_id: str) -> ConfigChangeProposal:
        assert proposal_id == "abc123"
        self.proposal.status = "approved"
        return self.proposal

    def reject_proposal(self, proposal_id: str) -> ConfigChangeProposal:
        assert proposal_id == "abc123"
        self.proposal.status = "rejected"
        return self.proposal


def test_config_proposal_panel_renders_approve_and_reject_actions(monkeypatch):
    service = FakeConfigChangeService()
    monkeypatch.setattr(ops_router, "_get_config_change_service", lambda: service)

    response = TestClient(create_app()).get("/api/config/proposals/panel")

    assert response.status_code == 200
    assert "添加估值路由: 家电" in response.text
    assert 'hx-post="/api/config/proposals/abc123/approve"' in response.text
    assert 'hx-post="/api/config/proposals/abc123/reject"' in response.text
    assert 'data-lucide="check"' in response.text
    assert 'data-lucide="x"' in response.text


def test_config_proposal_approve_endpoint_rerenders_panel(monkeypatch):
    service = FakeConfigChangeService()
    called = {"reset": False}
    monkeypatch.setattr(ops_router, "_get_config_change_service", lambda: service)
    monkeypatch.setattr(
        ops_router,
        "_reset_runtime_services",
        lambda: called.__setitem__("reset", True),
    )

    response = TestClient(create_app()).post("/api/config/proposals/abc123/approve")

    assert response.status_code == 200
    assert "已应用" in response.text
    assert called["reset"] is True


def test_config_proposal_reject_endpoint_rerenders_panel(monkeypatch):
    service = FakeConfigChangeService()
    monkeypatch.setattr(ops_router, "_get_config_change_service", lambda: service)

    response = TestClient(create_app()).post("/api/config/proposals/abc123/reject")

    assert response.status_code == 200
    assert "已搁置" in response.text

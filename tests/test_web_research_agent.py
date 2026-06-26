from fastapi.testclient import TestClient

import sentinel.web.routers.ops as ops_router
from sentinel.web.main import create_app
from sentinel.web.services.research_agent_service import ResearchAgentService


class FakeSignalCollector:
    def ensure_daily_snapshot(self):
        return {"items": []}


def test_research_agent_panel_auto_runs_today_review(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text(
        'last_updated: "2026-05-01"\ncompanies: {}\n',
        encoding="utf-8",
    )
    (config_dir / "policy_whitelist.yaml").write_text(
        'last_updated: "2026-05-01"\nsectors: {}\n',
        encoding="utf-8",
    )
    (config_dir / "ecosystem_themes.yaml").write_text(
        "hot_themes: [AI]\nrole_premiums: {}\n",
        encoding="utf-8",
    )
    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        artifact_root=tmp_path / "research_runs",
        today="2026-06-17",
    )
    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: service)
    monkeypatch.setattr(ops_router, "_get_signal_collector_service", lambda: FakeSignalCollector())

    response = TestClient(create_app()).get("/api/research-agent/panel")

    assert response.status_code == 200
    assert "只读建议模式" in response.text
    assert "政策白名单需要复核" in response.text
    assert 'hx-post="/api/research-agent/run"' in response.text


def test_research_agent_run_endpoint_renders_suggestions(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text(
        'last_updated: "2026-05-01"\ncompanies: {}\n',
        encoding="utf-8",
    )
    (config_dir / "policy_whitelist.yaml").write_text(
        'last_updated: "2026-05-01"\nsectors: {}\n',
        encoding="utf-8",
    )
    (config_dir / "ecosystem_themes.yaml").write_text(
        "hot_themes: [AI]\nrole_premiums: {}\n",
        encoding="utf-8",
    )
    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        artifact_root=tmp_path / "research_runs",
        today="2026-06-17",
    )
    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: service)

    response = TestClient(create_app()).post("/api/research-agent/run")

    assert response.status_code == 200
    assert "只读建议模式" in response.text
    assert "政策白名单需要复核" in response.text
    assert "反向证据" in response.text
    assert "跳转处理" in response.text
    assert 'hx-post="/api/research-agent/collect"' in response.text
    assert 'hx-get="/api/config/load/policy_whitelist.yaml"' in response.text
    assert 'hx-target="#config-editor-container"' in response.text


def test_research_agent_status_endpoint_updates_suggestion(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text(
        'last_updated: "2026-05-01"\ncompanies: {}\n',
        encoding="utf-8",
    )
    (config_dir / "policy_whitelist.yaml").write_text(
        'last_updated: "2026-05-01"\nsectors: {}\n',
        encoding="utf-8",
    )
    (config_dir / "ecosystem_themes.yaml").write_text(
        "hot_themes: [AI]\nrole_premiums: {}\n",
        encoding="utf-8",
    )
    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        artifact_root=tmp_path / "research_runs",
        today="2026-06-17",
    )
    run = service.run_daily_review()
    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: service)

    response = TestClient(create_app()).post(
        f"/api/research-agent/suggestions/{run.suggestions[0].id}/status",
        data={"status": "queued"},
    )

    assert response.status_code == 200
    assert "已加入待办" in response.text


def test_research_agent_collect_endpoint_refreshes_external_signals(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text(
        'last_updated: "2026-06-20"\ncompanies: {}\n',
        encoding="utf-8",
    )
    (config_dir / "policy_whitelist.yaml").write_text(
        'last_updated: "2026-06-20"\nsectors: {}\n',
        encoding="utf-8",
    )
    (config_dir / "ecosystem_themes.yaml").write_text(
        'last_updated: "2026-06-20"\nnegative_watchlist: []\n',
        encoding="utf-8",
    )
    service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        external_signal_path=tmp_path / "research_external_signals.json",
        artifact_root=tmp_path / "research_runs",
        today="2026-06-23",
    )

    class FakeCollector:
        def collect(self):
            (tmp_path / "research_external_signals.json").write_text(
                """{
  "generated_at": "2026-06-23T08:00:00",
  "items": [
    {
      "category": "policy",
      "source": "官方政策RSS",
      "title": "人工智能+行动持续推进",
      "published_at": "2026-06-22",
      "sectors": ["人工智能"],
      "url": "https://example.test/policy-ai",
      "impact": "高"
    }
  ]
}""",
                encoding="utf-8",
            )
            return {"items": [{"title": "人工智能+行动持续推进"}]}

    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: service)
    monkeypatch.setattr(ops_router, "_get_signal_collector_service", lambda: FakeCollector())

    response = TestClient(create_app()).post("/api/research-agent/collect")

    assert response.status_code == 200
    assert "外部信号已更新" in response.text
    assert "政策白名单有新外部信号待复核" in response.text
    assert "官方政策RSS" in response.text

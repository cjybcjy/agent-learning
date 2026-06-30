from fastapi.testclient import TestClient

import sentinel.web.routers.ops as ops_router
from sentinel.web.main import create_app
from sentinel.web.services.config_change_service import ConfigChangeService
from sentinel.web.services.config_change_service import ConfigChangeProposal
from sentinel.web.services.research_agent_service import EvidenceItem
from sentinel.web.services.research_agent_service import ResearchAgentRun
from sentinel.web.services.research_agent_service import ResearchAgentService
from sentinel.web.services.research_agent_service import ResearchSuggestion


class FakeSignalCollector:
    def ensure_daily_snapshot(self):
        return {"items": []}


def test_review_queue_panel_combines_agent_suggestions_and_config_proposals(monkeypatch):
    suggestion = ResearchSuggestion(
        id="suggestion-1",
        category="external_policy",
        title="政策白名单有新外部信号待复核",
        target="人工智能",
        config_file="policy_whitelist.yaml",
        rationale="外部政策快照出现新增支持信号。",
        proposed_change="加入政策复核项",
        confidence=0.82,
        impact="高",
        evidence=[
            EvidenceItem(
                source="官方政策RSS",
                title="人工智能+行动持续推进",
                detail="2026-06-23",
            )
        ],
        counter_evidence=[],
    )
    run = ResearchAgentRun(
        run_id="RA_TEST",
        generated_at="2026-06-30T09:00:00",
        mode="read_only_advisory",
        status="completed",
        summary="1 条建议待复核",
        source_mix={"internal_config": 3, "contrarian_checks": 0, "external_news": 1},
        suggestions=[suggestion],
    )
    proposal = ConfigChangeProposal(
        id="proposal-1",
        action="add",
        title="添加政策复核项",
        config_file="policy_whitelist.yaml",
        path="review_queue.ai_policy",
        current_value=None,
        proposed_value={"target": "人工智能"},
        rationale="来自 Agent 建议的人工确认项。",
    )

    class FakeAgentService:
        def ensure_daily_review(self):
            return run

    class FakeConfigChangeService:
        def scan_proposals(self):
            return [proposal]

    monkeypatch.setattr(ops_router, "_get_signal_collector_service", lambda: FakeSignalCollector())
    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: FakeAgentService())
    monkeypatch.setattr(ops_router, "_get_config_change_service", lambda: FakeConfigChangeService())

    response = TestClient(create_app()).get("/api/review-queue/panel")

    assert response.status_code == 200
    assert "待复核事项" in response.text
    assert "来源" in response.text
    assert "建议" in response.text
    assert "影响" in response.text
    assert "操作" in response.text
    assert "外部信号 / Agent" in response.text
    assert "配置确认" in response.text
    assert "政策白名单有新外部信号待复核" in response.text
    assert "添加政策复核项" in response.text
    assert 'hx-post="/api/review-queue/suggestions/suggestion-1/queue-confirmation"' in response.text
    assert 'hx-post="/api/review-queue/proposals/proposal-1/approve"' in response.text


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
    assert "加入确认名单" in response.text
    assert "打开 YAML" in response.text
    assert 'hx-post="/api/research-agent/collect"' in response.text
    assert 'hx-post="/api/research-agent/suggestions/' in response.text
    assert "/queue-confirmation" in response.text
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


def test_research_agent_queue_confirmation_endpoint_renders_proposal_panel(
    tmp_path,
    monkeypatch,
):
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
    agent_service = ResearchAgentService(
        config_dir=config_dir,
        store_path=tmp_path / "agent_runs.json",
        artifact_root=tmp_path / "research_runs",
        today="2026-06-17",
    )
    run = agent_service.run_daily_review()
    suggestion = next(item for item in run.suggestions if item.config_file == "policy_whitelist.yaml")
    change_service = ConfigChangeService(
        config_dir=config_dir,
        store_path=tmp_path / "config_change_decisions.json",
    )
    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: agent_service)
    monkeypatch.setattr(ops_router, "_get_config_change_service", lambda: change_service)

    response = TestClient(create_app()).post(
        f"/api/research-agent/suggestions/{suggestion.id}/queue-confirmation"
    )

    assert response.status_code == 200
    assert "半自动确认" in response.text
    assert "添加政策复核项" in response.text
    assert 'hx-post="/api/config/proposals/' in response.text


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

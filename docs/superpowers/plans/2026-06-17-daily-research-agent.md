# Daily Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only daily research agent to the MGFS Ops workspace that generates evidence-backed configuration suggestions without editing YAML files.

**Architecture:** Implement a small service in `sentinel/web/services/research_agent_service.py` that reads YAML configs, generates deterministic suggestion objects, and persists the latest run as JSON. Expose it through `sentinel/web/routers/ops.py` and render the result with an HTMX partial in the existing Ops dashboard.

**Tech Stack:** Python dataclasses, PyYAML, FastAPI, Jinja2, HTMX, pytest, FastAPI TestClient.

---

## File Structure

- Create `sentinel/web/services/research_agent_service.py`: dataclasses, suggestion generation, JSON persistence, status updates.
- Create `sentinel/web/templates/partials/research_agent_panel.html`: empty state, run summary, source mix, suggestion cards, action buttons.
- Modify `sentinel/web/routers/ops.py`: add service accessor and three endpoints for panel load, run, and status update.
- Modify `sentinel/web/templates/ops.html`: add Agent step to workflow guide and mount the Agent panel before config editing.
- Modify `sentinel/web/templates/base.html`: add compact styles for Agent suggestion cards.
- Create `tests/test_research_agent_service.py`: service-level TDD coverage.
- Modify `tests/test_web_workstation_ui.py`: Ops page includes the Agent step and panel mount.
- Create `tests/test_web_research_agent.py`: API and partial rendering coverage.

## Task 1: Service Tests

**Files:**
- Create: `tests/test_research_agent_service.py`
- Create after RED: `sentinel/web/services/research_agent_service.py`

- [ ] **Step 1: Write failing service tests**

```python
from pathlib import Path

import yaml

from sentinel.web.services.research_agent_service import ResearchAgentService


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")


def test_daily_review_flags_stale_configs_and_theme_concentration(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_yaml(config_dir / "policy_whitelist.yaml", {"last_updated": "2026-05-01", "sectors": {"半导体": {"multiplier": 1.2}}})
    _write_yaml(config_dir / "ecosystem_themes.yaml", {"hot_themes": ["AI_Compute_Infrastructure"], "role_premiums": {"core_arena": -0.05}})
    _write_yaml(config_dir / "moat_static_base.yaml", {
        "last_updated": "2026-05-01",
        "companies": {
            "000001": {"theme": "AI_Compute_Infrastructure", "sector": "银行", "base_score": {}},
            "000002": {"theme": "AI_Compute_Infrastructure", "sector": "地产", "base_score": {}},
            "000003": {"theme": "Consumer_Staples", "sector": "食品饮料", "base_score": {}},
        },
    })

    service = ResearchAgentService(config_dir=config_dir, store_path=tmp_path / "agent_runs.json", today="2026-06-17")
    run = service.run_daily_review()

    titles = [item.title for item in run.suggestions]
    assert "政策白名单需要复核" in titles
    assert "主题覆盖过于集中" in titles
    assert "生态主题缺少反向观察池" in titles
    assert run.mode == "read_only_advisory"
    assert run.source_mix["internal_config"] >= 3
    assert all(item.counter_evidence for item in run.suggestions)


def test_daily_review_persists_latest_run_and_status_without_editing_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    moat_path = config_dir / "moat_static_base.yaml"
    original_moat = {"last_updated": "2026-05-01", "companies": {"000001": {"theme": "AI", "sector": "银行", "base_score": {}}}}
    _write_yaml(moat_path, original_moat)
    _write_yaml(config_dir / "policy_whitelist.yaml", {"last_updated": "2026-05-01", "sectors": {}})
    _write_yaml(config_dir / "ecosystem_themes.yaml", {"hot_themes": ["AI"], "role_premiums": {}})

    service = ResearchAgentService(config_dir=config_dir, store_path=tmp_path / "agent_runs.json", today="2026-06-17")
    run = service.run_daily_review()
    updated = service.update_suggestion_status(run.suggestions[0].id, "watching")

    latest = service.load_latest_run()
    assert latest is not None
    assert updated.status == "watching"
    assert any(item.status == "watching" for item in latest.suggestions)
    assert yaml.safe_load(moat_path.read_text(encoding="utf-8")) == original_moat
```

- [ ] **Step 2: Run service tests to verify RED**

Run: `PYTHONPATH=. pytest tests/test_research_agent_service.py -q`

Expected: FAIL with `ModuleNotFoundError` or import error for `research_agent_service`.

## Task 2: Service Implementation

**Files:**
- Create: `sentinel/web/services/research_agent_service.py`

- [ ] **Step 1: Implement service dataclasses and JSON persistence**

Create dataclasses `EvidenceItem`, `ResearchSuggestion`, `ResearchAgentRun`, plus `ResearchAgentService.run_daily_review()`, `load_latest_run()`, and `update_suggestion_status()`.

- [ ] **Step 2: Implement deterministic suggestion checks**

Implement:
- `_freshness_suggestion()` for missing or stale `last_updated`.
- `_theme_concentration_suggestion()` for top theme share >= 40%.
- `_ecosystem_counter_bias_suggestion()` when no negative watchlist or contrarian field exists.
- `_persist_run()` and `_read_payload()` for JSON snapshots.

- [ ] **Step 3: Run service tests to verify GREEN**

Run: `PYTHONPATH=. pytest tests/test_research_agent_service.py -q`

Expected: PASS.

## Task 3: Web Tests

**Files:**
- Create: `tests/test_web_research_agent.py`
- Modify: `tests/test_web_workstation_ui.py`

- [ ] **Step 1: Write failing route and page tests**

```python
from fastapi.testclient import TestClient

import sentinel.web.routers.ops as ops_router
from sentinel.web.main import create_app
from sentinel.web.services.research_agent_service import ResearchAgentService


def test_ops_page_mounts_daily_research_agent():
    response = TestClient(create_app()).get("/dashboard/ops")
    assert response.status_code == 200
    assert "每日研究 Agent" in response.text
    assert 'hx-get="/api/research-agent/panel"' in response.text
    assert 'href="#daily-research-agent"' in response.text


def test_research_agent_run_endpoint_renders_suggestions(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "moat_static_base.yaml").write_text('last_updated: "2026-05-01"\\ncompanies: {}\\n', encoding="utf-8")
    (config_dir / "policy_whitelist.yaml").write_text('last_updated: "2026-05-01"\\nsectors: {}\\n', encoding="utf-8")
    (config_dir / "ecosystem_themes.yaml").write_text("hot_themes: [AI]\\nrole_premiums: {}\\n", encoding="utf-8")
    service = ResearchAgentService(config_dir=config_dir, store_path=tmp_path / "agent_runs.json", today="2026-06-17")
    monkeypatch.setattr(ops_router, "_get_research_agent_service", lambda: service)

    response = TestClient(create_app()).post("/api/research-agent/run")

    assert response.status_code == 200
    assert "只读建议模式" in response.text
    assert "政策白名单需要复核" in response.text
    assert "反向证据" in response.text
```

- [ ] **Step 2: Run web tests to verify RED**

Run: `PYTHONPATH=. pytest tests/test_web_research_agent.py tests/test_web_workstation_ui.py -q`

Expected: FAIL because routes and Ops panel are missing.

## Task 4: Routes and Templates

**Files:**
- Modify: `sentinel/web/routers/ops.py`
- Modify: `sentinel/web/templates/ops.html`
- Create: `sentinel/web/templates/partials/research_agent_panel.html`
- Modify: `sentinel/web/templates/base.html`

- [ ] **Step 1: Add service accessor and routes**

Add `_research_agent_svc`, `_get_research_agent_service()`, and routes:
- `GET /research-agent/panel`
- `POST /research-agent/run`
- `POST /research-agent/suggestions/{suggestion_id}/status`

- [ ] **Step 2: Add Ops panel mount**

Add workflow step `1 每日研究 Agent`, shift existing steps to `2 配置规则`, `3 执行巡检`, `4 复盘修正`, and mount a panel with `id="daily-research-agent"` and `hx-get="/api/research-agent/panel"`.

- [ ] **Step 3: Add partial and styles**

Render empty state when no run exists. Render run metadata, source mix, and suggestion cards with status action buttons when a run exists.

- [ ] **Step 4: Run web tests to verify GREEN**

Run: `PYTHONPATH=. pytest tests/test_web_research_agent.py tests/test_web_workstation_ui.py -q`

Expected: PASS.

## Task 5: Final Verification

**Files:**
- No new files unless fixes are required.

- [ ] **Step 1: Run focused web suite**

Run: `PYTHONPATH=. pytest tests/test_web_*.py tests/test_research_agent_service.py -q`

Expected: PASS.

- [ ] **Step 2: Smoke test HTML endpoints**

Run:

```bash
curl -s http://127.0.0.1:8000/dashboard/ops | rg "每日研究 Agent|research-agent/panel"
curl -s -X POST http://127.0.0.1:8000/api/research-agent/run | rg "只读建议模式|反向证据"
```

Expected: both commands print matching HTML snippets.

## Self-Review

- Spec coverage: daily run, read-only suggestions, evidence/counter-evidence, source mix, status updates, Ops UI, and no YAML writes are covered.
- Placeholder scan: no placeholder language is present.
- Type consistency: service names and route names are consistent across tests, implementation tasks, and templates.

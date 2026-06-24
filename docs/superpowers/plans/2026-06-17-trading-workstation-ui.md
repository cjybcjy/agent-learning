# Trading Workstation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the MGFS Web Dashboard into a componentized trading workstation that supports opportunity discovery, decision review, shadow positions, risk monitoring, calibration, and operations.

**Architecture:** Keep the existing FastAPI + Jinja2 + HTMX server-rendered architecture. Redesign templates and partials around a reusable workstation shell and panel styling while preserving all existing route IDs and HTMX targets.

**Tech Stack:** FastAPI, Jinja2, HTMX, Tailwind CDN, Lucide Icons, ECharts, pytest.

---

## File Structure

- Modify: `sentinel/web/templates/base.html` — workstation shell, navigation labels, shared CSS tokens.
- Modify: `sentinel/web/templates/research.html` — command-center grid and component placement.
- Modify: `sentinel/web/templates/ops.html` — system control console layout.
- Modify: `sentinel/web/templates/partials/decision_card.html` — denser decision ticket styling.
- Modify: `sentinel/web/templates/partials/risk_alert_banner.html` — risk-console styling.
- Modify: `sentinel/web/templates/partials/calibration_report.html` — calibration panel styling.
- Modify: `sentinel/web/templates/partials/scan_matrix.html` — matrix panel styling.
- Modify: `sentinel/web/templates/partials/pipeline_history.html` — pipeline monitor styling.
- Modify: `.gitignore` — ignore Superpowers visual companion artifacts and pytest cache.
- Delete: `EOF`, `PYEOF` — empty temporary files.
- Create: `tests/test_web_workstation_ui.py` — route-level UI contract tests.

## Task 1: Add UI Contract Tests

**Files:**
- Create: `tests/test_web_workstation_ui.py`

- [ ] **Step 1: Write failing tests**

```python
from fastapi.testclient import TestClient

from sentinel.web.main import create_app


def test_research_page_renders_trading_workstation_components():
    client = TestClient(create_app())

    response = client.get("/dashboard/research")

    assert response.status_code == 200
    assert "MGFS 交易工作站" in response.text
    assert "机会雷达" in response.text
    assert "决策票据" in response.text
    assert "组合风控" in response.text
    assert "贝叶斯校准" in response.text
    assert 'id="eval-result"' in response.text
    assert 'id="scan-result"' in response.text
    assert 'hx-get="/api/risk/alerts"' in response.text


def test_ops_page_renders_system_console_components():
    client = TestClient(create_app())

    response = client.get("/dashboard/ops")

    assert response.status_code == 200
    assert "系统控制台" in response.text
    assert "配置控制台" in response.text
    assert "流水线监控" in response.text
    assert 'id="config-editor-container"' in response.text
    assert 'id="pipeline-section"' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web_workstation_ui.py -q`

Expected: FAIL because the current templates do not render the new workstation labels.

## Task 2: Implement Workstation Shell and Research Workspace

**Files:**
- Modify: `sentinel/web/templates/base.html`
- Modify: `sentinel/web/templates/research.html`

- [ ] **Step 1: Replace the base shell**

Create shared CSS classes for `app-shell`, `sidebar`, `command-bar`, `workstation-panel`, `status-chip`, `metric-tile`, `terminal-table`, and responsive grids. Keep CDN imports and the existing ECharts/HTMX JavaScript hooks.

- [ ] **Step 2: Rebuild `research.html`**

Arrange existing HTMX components into:

- `risk-console`
- `opportunity-radar`
- `decision-ticket`
- `position-dock`
- `calibration-lab`
- `scan-result`

Preserve these IDs exactly: `eval-result`, `scan-started`, `scan-progress`, `scan-progress-bar`, `scan-progress-text`, `scan-result`.

- [ ] **Step 3: Run UI contract tests**

Run: `pytest tests/test_web_workstation_ui.py -q`

Expected: research test passes; ops test may still fail until Task 3.

## Task 3: Implement Ops Console

**Files:**
- Modify: `sentinel/web/templates/ops.html`
- Modify: `sentinel/web/templates/partials/pipeline_history.html`

- [ ] **Step 1: Rebuild ops page**

Use `系统控制台` as the page title. Place configuration loaders in `配置控制台` and the pipeline history in `流水线监控`.

- [ ] **Step 2: Keep endpoint targets stable**

Preserve `id="config-editor-container"` and `id="pipeline-section"` so existing tests and HTMX behavior remain compatible.

- [ ] **Step 3: Run UI contract tests**

Run: `pytest tests/test_web_workstation_ui.py -q`

Expected: PASS.

## Task 4: Polish Dynamic Partials

**Files:**
- Modify: `sentinel/web/templates/partials/decision_card.html`
- Modify: `sentinel/web/templates/partials/risk_alert_banner.html`
- Modify: `sentinel/web/templates/partials/calibration_report.html`
- Modify: `sentinel/web/templates/partials/scan_matrix.html`

- [ ] **Step 1: Apply workstation panel styling**

Use compact labels, table styling, semantic borders, and Lucide icons where existing markup already includes icon hooks.

- [ ] **Step 2: Preserve dynamic behavior**

Keep all HTMX attributes, ECharts container IDs, and `document.body.dispatchEvent(new Event('render-echarts'))` calls.

- [ ] **Step 3: Run relevant existing tests**

Run:

```bash
pytest tests/test_web_eval_single.py tests/test_web_scan.py tests/test_web_risk_alerts.py tests/test_web_calibration.py -q
```

Expected: PASS.

## Task 5: Cleanup

**Files:**
- Modify: `.gitignore`
- Delete: `EOF`
- Delete: `PYEOF`

- [ ] **Step 1: Ignore generated artifacts**

Add `.pytest_cache/` and `.superpowers/` to `.gitignore`.

- [ ] **Step 2: Remove empty temporary files**

Delete root-level `EOF` and `PYEOF`.

- [ ] **Step 3: Remove runtime caches**

Remove generated `__pycache__` and `.pytest_cache` directories from the working tree.

## Task 6: Full Verification

**Files:**
- All modified web templates and tests.

- [ ] **Step 1: Run web tests**

Run: `pytest tests/test_web_*.py -q`

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run: `pytest -q`

Expected: PASS or report unrelated pre-existing failures with exact failing tests.

- [ ] **Step 3: Start local server**

Run: `uvicorn sentinel.web.main:app --host 127.0.0.1 --port 3002`

Expected: server listens on `http://localhost:3002`.

- [ ] **Step 4: Smoke-check rendered pages**

Run:

```bash
curl -s http://localhost:3002/dashboard/research | rg "MGFS 交易工作站|机会雷达|决策票据|组合风控"
curl -s http://localhost:3002/dashboard/ops | rg "系统控制台|配置控制台|流水线监控"
```

Expected: both commands print matching labels.

## Self-Review

- Spec coverage: the plan covers research workspace, ops console, dynamic partials, cleanup, and verification.
- Placeholder scan: no unfinished placeholder markers remain.
- Type consistency: the plan only changes Jinja templates and route-level tests, preserving existing Python route signatures and HTMX target IDs.

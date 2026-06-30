# Kelly Shadow Position Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only Kelly shadow position simulator with manual candidate entry, latest-price refresh, risk scanning, and snapshot evidence for strategy optimization.

**Architecture:** Reuse `PositionSizingEngine` for Kelly sizing, `MGFSRepository` for active holdings and snapshots, `StopLossMonitor` for risk alerts, and existing OHLCV fetchers for latest prices. Add a focused `ShadowPositionSimulatorService` as the orchestration boundary, then expose it through HTMX endpoints and the Research Dashboard Position Dock.

**Tech Stack:** FastAPI, Jinja2/HTMX, DuckDB repository, pytest, existing MGFS execution/data modules.

---

### Task 1: Snapshot Persistence

**Files:**
- Modify: `sentinel/mgfs/storage/mgfs_repository.py`
- Modify: `tests/test_mgfs_repository.py`

- [ ] Add `mgfs_shadow_position_snapshots` to the bootstrap DDL.
- [ ] Add `save_shadow_position_snapshot(...)`.
- [ ] Add `list_shadow_position_snapshots(symbol: str | None = None, limit: int = 100)`.
- [ ] Test that a snapshot can be saved and queried by symbol.

### Task 2: Kelly Simulator Service

**Files:**
- Create: `sentinel/web/services/shadow_position_service.py`
- Create: `tests/test_shadow_position_service.py`

- [ ] Create dataclasses for candidate preview rows, portfolio preview, refresh failures, and refresh results.
- [ ] Implement latest price lookup through an injected `PriceFetcher`.
- [ ] Implement `preview_candidates()` using `PositionSizingEngine`.
- [ ] Implement `confirm_candidates()` to save Kelly-derived active holdings.
- [ ] Implement `refresh_active_holdings(source)` to update prices, write snapshots, and return stop-loss alerts.
- [ ] Test preview validation, confirm persistence, successful refresh, and one-symbol refresh failure.

### Task 3: Web Routes And Partials

**Files:**
- Modify: `sentinel/web/routers/ops.py`
- Create: `sentinel/web/templates/partials/shadow_position_panel.html`
- Create: `sentinel/web/templates/partials/shadow_position_preview.html`
- Create: `sentinel/web/templates/partials/shadow_position_holdings.html`
- Modify: `tests/test_web_paper_trade.py`

- [ ] Add `_get_shadow_position_service()`.
- [ ] Add `GET /api/shadow-positions/panel`.
- [ ] Add `POST /api/shadow-positions/preview`.
- [ ] Add `POST /api/shadow-positions/confirm`.
- [ ] Add `POST /api/shadow-positions/refresh`.
- [ ] Test that preview renders Kelly weights and confirm/refresh call the service.

### Task 4: Research Dashboard Integration

**Files:**
- Modify: `sentinel/web/templates/research.html`
- Modify: `tests/test_web_workstation_ui.py`

- [ ] Replace the static Position Dock body with an HTMX-loaded simulator panel.
- [ ] Keep the workstation layout compact and consistent with existing controls.
- [ ] Test that the Research page wires `hx-get="/api/shadow-positions/panel"`.

### Task 5: Pipeline Refresh Integration

**Files:**
- Modify: `sentinel/web/services/pipeline_service.py`
- Modify: `tests/test_pipeline_stop_loss_integration.py`

- [ ] Add a post-pipeline shadow refresh method.
- [ ] Call it after a completed pipeline with `refresh_source="pipeline"`.
- [ ] Keep the existing stop-loss scan path working for backwards compatibility.
- [ ] Test that pipeline completion invokes the shadow refresh service.

### Task 6: Verification

**Files:**
- No new source files.

- [ ] Run service and router tests:
  `PYTHONPATH=. pytest tests/test_shadow_position_service.py tests/test_web_paper_trade.py tests/test_pipeline_stop_loss_integration.py -q`
- [ ] Run related dashboard tests:
  `PYTHONPATH=. pytest tests/test_web_workstation_ui.py tests/test_web_calibration.py -q`
- [ ] Verify the running page:
  `curl --noproxy '*' -sS http://127.0.0.1:8000/dashboard/research | rg "shadow-positions/panel|Position Dock|影子持仓"`
- [ ] Verify no whitespace errors:
  `git diff --check`

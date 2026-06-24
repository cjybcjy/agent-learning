# MGFS Trading Workstation UI Design

## Purpose

The `company_value_analysis_system` branch is evolving MGFS from a CLI/reporting tool into a full decision loop: discover opportunities, evaluate a target, create a shadow position, monitor risk, and calibrate future scoring. The UI should make that strategy visible as a trading-style workstation without pretending to be a live order-entry terminal.

## Market References

- Interactive Brokers Risk Navigator emphasizes real-time risk exposure, spreadsheet-like scanning, and drill-down views.
- Bloomberg PORT frames portfolio analytics as one place for positions, risk, and performance.
- TradingView screeners focus on filterable opportunity discovery with table and chart views.
- thinkorswim combines scan, analyze, and risk-profile tools for strategy evaluation.

MGFS should borrow the operating model, not the full density of a professional terminal. The interface should be compact, risk-aware, and componentized, while staying readable for a single operator.

## Approved Direction

Use a multi-component trading workstation. The primary screen follows the recommended command-center grid:

- Top command bar for system state and strategy loop.
- Risk console as the first visible live status.
- Opportunity radar for ecosystem scanning and single-symbol input.
- Decision ticket for current evaluation output.
- Portfolio/risk dock for shadow position and alert actions.
- Calibration lab for Bayesian score review.
- Operations console for configuration and pipeline execution.

The user explicitly approved option C, with separate components for each strategic loop. The implementation combines the proposed A layout as the main workspace with B/C concepts as component groups.

## Information Architecture

### Research Route: `/dashboard/research`

Display label: `交易工作站`.

Components:

- `Global Command Bar`: current strategy mode, risk posture, calibration status, branch label.
- `Risk Console`: HTMX-loaded stop-loss and portfolio alerts.
- `Opportunity Radar`: single-symbol evaluator controls and ecosystem scan controls.
- `Decision Ticket`: empty state until evaluation, then renders the existing decision card.
- `Shadow Position Dock`: explains and hosts actions produced from decision cards.
- `Calibration Lab`: HTMX-loaded Bayesian calibration report.
- `Scan Result Matrix`: HTMX ecosystem scatter/table result.

### Ops Route: `/dashboard/ops`

Display label: `系统控制台`.

Components:

- `Config Console`: grouped YAML configuration loaders.
- `Pipeline Monitor`: manual market sweep trigger, batch table, drill-down rows, CSV export.
- `Operational Notes`: concise state markers for hot reload, validation, and audit trail.

## Interaction Model

All existing endpoints remain compatible:

- `POST /api/eval/single` fills `#eval-result`.
- `POST /api/scan/start` starts background scan and fills `#scan-started`.
- `GET /api/scan/progress/{task_id}` updates progress.
- `GET /api/scan/result/{task_id}` fills `#scan-result`.
- `GET /api/risk/alerts` refreshes the risk console.
- `POST /api/paper_trade` creates a shadow position from eligible decision cards.
- `GET /api/calibration/reports` fills calibration.
- `GET/POST /api/config/*` and `GET/POST /api/pipeline/*` remain in the ops route.

## Visual System

- Palette: slate workspace, white panels, blue command accents, green/yellow/red semantic states.
- Density: more compact than the current card stack, but not terminal-cramped.
- Shape: panels use 8px radius or less; repeated containers are panels, not nested decorative cards.
- Typography: clear operational labels, tabular numbers for scores and risk values.
- Icons: continue Lucide icons for navigation and tool buttons.
- Layout: desktop-first grid with responsive collapse to one column on narrow screens.

## Error and Empty States

- Loading states remain visible inside the relevant component.
- Empty decision state tells the user where the next evaluation will appear.
- Empty scan state stays attached to the opportunity radar, not a disconnected page bottom.
- Risk normal state should read as an operational status, not a decorative success banner.

## Cleanup Scope

Safe cleanup is limited to:

- Root-level temporary files with no content or references.
- Generated cache directories and ignored runtime artifacts.
- Obvious stale UI labels after route relabeling.
- Dead imports only when tests confirm they are not part of public behavior.

No domain logic, scoring formulas, fetcher logic, or persistence behavior should be removed as part of this UI pass.

## Acceptance Criteria

- `/dashboard/research` renders `MGFS 交易工作站`, `机会雷达`, `决策票据`, `组合风控`, and `贝叶斯校准`.
- `/dashboard/ops` renders `系统控制台`, `配置控制台`, and `流水线监控`.
- Existing HTMX endpoint targets remain present.
- Existing web tests still pass.
- New UI tests prove the workstation labels and component anchors render.
- Local server runs on a non-conflicting port and exposes the redesigned UI.

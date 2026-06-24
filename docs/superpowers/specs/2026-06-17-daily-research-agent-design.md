# Daily Research Agent Design

## Goal

Build a read-only daily research agent for the MGFS ops workspace. The agent should reduce manual configuration bias by producing a daily suggestion sheet with evidence, counter-evidence, confidence, and impact, while never writing to YAML configuration files without human review.

## Strategic Intent

The current ops flow makes the user choose and edit configuration files directly. That is powerful, but it can reinforce the user's existing view of the market. The new agent adds an independent review loop before configuration edits:

1. Scan local MGFS configuration freshness and coverage.
2. Identify stale policy/theme assumptions and concentrated exposures.
3. Produce suggestions with both supporting evidence and caveats.
4. Let the user mark each suggestion as queued, watching, or rejected.
5. Keep the manual YAML editor as the final authority.

## User Workflow

The Ops workflow becomes:

1. **每日研究 Agent**: run today's read-only review and inspect suggestions.
2. **配置规则**: open the YAML editor only after a suggestion is worth acting on.
3. **执行巡检**: run the pipeline after configuration changes.
4. **复盘修正**: use calibration reports to validate whether the change helped.

## Product Behavior

- A new Ops panel named `每日研究 Agent` appears between the workflow guide and the configuration console.
- The panel loads the latest agent run with `GET /api/research-agent/panel`.
- The user can trigger a fresh run with `POST /api/research-agent/run`.
- Suggestions are generated from local config files and persisted as a JSON run snapshot under the app data directory.
- Each suggestion contains:
  - stable id
  - category
  - title
  - target
  - config file
  - rationale
  - proposed change
  - confidence
  - impact
  - evidence list
  - counter-evidence list
  - handling status
- The user can mark a suggestion as:
  - `queued`: worth reviewing in the YAML editor
  - `watching`: keep observing
  - `rejected`: not relevant now

## Anti-Information-Bubble Rules

- Agent output must include counter-evidence or a source limitation for every suggestion.
- Agent output must show source mix, including internal config and contrarian checks.
- Agent must not auto-apply YAML edits.
- The UI must say clearly that manual confirmation is required before config changes.
- The first version should avoid fragile live scraping. It should be deterministic and cron-ready, with room to add live policy/news connectors in a follow-up integration.

## First-Version Suggestion Logic

The first version produces suggestions from local configuration:

- **Freshness review**: flag config files whose `last_updated` is missing or older than 21 days.
- **Theme concentration review**: flag moat config when one theme accounts for at least 40% of covered companies.
- **Counter-bias scaffold**: flag ecosystem config when no explicit negative watchlist / contrarian field exists.
- **Policy review**: flag stale policy whitelist assumptions.

## Non-Goals

- No live market trading.
- No automatic YAML edits.
- No external news scraping in this first implementation.
- No background scheduler inside FastAPI in this first implementation; the run endpoint and service are safe for future cron integration.

## Acceptance Criteria

- Ops page renders a visible `每日研究 Agent` panel and includes it in the workflow guide.
- `GET /api/research-agent/panel` returns an empty state before the first run.
- `POST /api/research-agent/run` creates a persisted read-only run with suggestions and source mix.
- Marking a suggestion updates only the saved run snapshot, not configuration files.
- Agent service tests verify stale config detection, concentration detection, counter-evidence presence, persistence, and status updates.
- Existing web tests continue to pass.

## Self-Review

- The feature is scoped to one subsystem: Ops daily research suggestions.
- The design preserves the existing manual configuration workflow.
- The data model avoids database migration risk while exposing a clean service boundary for a future repository table.
- The anti-bubble requirements are testable without relying on current external market data.

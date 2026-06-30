# Kelly Shadow Position Simulator Design

## Goal

Build a complete research-only Kelly shadow position simulator inside the Research
Dashboard. The simulator lets the user manually choose buy candidates, uses the
existing Kelly sizing engine to compute suggested weights, writes confirmed
positions into the shadow holdings store, refreshes market prices on demand or
after pipeline runs, triggers existing stop-loss monitoring, and records snapshots
that can later support strategy calibration.

This is not a live trading or broker order-entry system. It must not place real
orders, mutate YAML score config automatically, or turn alerts into direct
trading instructions.

## User Workflow

1. The user opens `Research Dashboard -> Position Dock`.
2. The user manually enters one or more candidates:
   - symbol
   - name
   - sector
   - final_score
   - payoff_ratio
3. The system fetches the latest available price for each candidate.
4. If a price cannot be fetched, the row remains editable and requires a manual
   price before it can be confirmed.
5. The user previews the Kelly portfolio:
   - computed win probability
   - payoff ratio
   - raw Kelly fraction
   - clipped final weight
   - cash reserve
   - hard stop, trailing stop, and portfolio stop settings
6. The user confirms the preview.
7. Confirmed rows are saved into `mgfs_active_holdings`.
8. The user can click refresh, or a pipeline run can call the same refresh
   service, to update prices and rerun risk checks.
9. Every refresh writes a shadow position snapshot for later optimization.

## Architecture

### Existing Components To Reuse

- `PositionSizingEngine` remains the source of Kelly sizing, sector exposure
  clipping, cash reserve handling, and stop-loss defaults.
- `MGFSRepository.save_active_holding()` remains the write path for active
  shadow holdings.
- `MGFSRepository.update_holding_price()` remains the current/highest price
  update primitive.
- `StopLossMonitor.scan()` remains the risk alert engine for hard stops,
  trailing stops, and portfolio-level emergency alerts.
- Existing market price fetchers should be reused where possible rather than
  adding a new vendor integration.

### New Service Boundary

Add a web-facing service, tentatively `ShadowPositionSimulatorService`, with
three responsibilities:

- `preview_candidates(candidates)`: validate manual candidate rows, fetch
  missing latest prices, call `PositionSizingEngine.build_portfolio()`, and
  return a preview model.
- `confirm_portfolio(preview)`: save selected preview holdings into
  `mgfs_active_holdings`.
- `refresh_active_holdings(source)`: fetch latest prices for all active
  holdings, update current/highest prices, write snapshots, and return updated
  risk alerts.

The service should keep price fetching, Kelly sizing, persistence, and risk
monitoring separate enough that each can be tested independently.

## Data Model

Add a snapshot table, tentatively `mgfs_shadow_position_snapshots`.

Suggested columns:

- `snapshot_id`
- `symbol`
- `name`
- `sector`
- `entry_price`
- `current_price`
- `highest_price`
- `weight`
- `kelly_fraction`
- `win_prob`
- `payoff_ratio`
- `unrealized_return`
- `drawdown_from_entry`
- `drawdown_from_high`
- `stop_loss_hard`
- `stop_loss_trailing`
- `portfolio_stop_loss`
- `hard_stop_triggered`
- `trailing_stop_triggered`
- `portfolio_stop_triggered`
- `refresh_source`
- `created_at`

`refresh_source` is either `manual` or `pipeline` in the first version.

The existing active holdings table can continue to be the current state table.
The snapshot table is the historical evidence ledger for optimization.

## UI Design

Replace the current static Position Dock copy with a compact workstation panel:

- Manual candidate rows with add/remove controls.
- Inputs for symbol, name, sector, final score, payoff ratio, and optional price.
- A preview button that renders computed weights and risk metadata.
- A confirm button that writes the preview into shadow holdings.
- A refresh prices button that updates active holdings and risk alerts.
- A small holdings/snapshot status area showing last refresh source and time.

The UI should use the existing workstation visual language:

- `ws-input` for numeric and text fields.
- `ws-button` for preview, confirm, and refresh actions.
- Existing metric tiles for total weight, cash reserve, and alert count.
- No broker-like language such as buy order, sell order, execution, or trade
  confirmation.

## Data Flow

### Preview

Manual candidate form -> `/api/shadow-positions/preview` ->
`ShadowPositionSimulatorService.preview_candidates()` -> price fetch ->
`PositionSizingEngine.build_portfolio()` -> preview partial.

### Confirm

Preview form -> `/api/shadow-positions/confirm` ->
`ShadowPositionSimulatorService.confirm_portfolio()` ->
`MGFSRepository.save_active_holding()` -> success partial and refreshed holdings.

### Refresh

Button or pipeline -> `ShadowPositionSimulatorService.refresh_active_holdings()`:

1. Load active holdings.
2. Fetch latest price per symbol.
3. Update current/highest price.
4. Compute return and drawdown metrics.
5. Write one snapshot per holding.
6. Run `StopLossMonitor.scan()`.
7. Return refreshed state to Position Dock and Risk Console.

## Error Handling

- Invalid symbols remain in the preview with a row-level error.
- Missing price data requires manual price input before confirmation.
- Invalid prices are rejected before persistence.
- Negative or zero payoff ratio is rejected before Kelly sizing.
- Candidates with negative expected value appear as zero-weight rows and are not
  saved as active holdings unless the user edits assumptions and previews again.
- If a refresh cannot fetch a latest price for one holding, keep the previous
  current price, record the failure in the UI, and continue refreshing other
  holdings.
- Snapshot write failures should not silently pass; the UI should show a clear
  warning because optimization evidence would be incomplete.

## Pipeline Integration

After a pipeline run completes, call the same refresh service with
`refresh_source="pipeline"`. This keeps manual refresh and pipeline refresh
behavior identical and prevents two separate price-update rules from drifting.

## Strategy Optimization Use

The snapshot table enables later analysis of:

- whether high MGFS final scores produce better shadow returns
- whether payoff assumptions are too optimistic or conservative
- whether Kelly weights are too aggressive
- whether sector limits are too loose or too restrictive
- whether hard/trailing stop thresholds trigger too early or too late

This first version only records the evidence. It does not automatically modify
Kelly parameters, sector caps, stop-loss thresholds, or YAML score config.

## Testing Plan

Unit tests:

- preview validates candidate rows and rejects invalid price/payoff inputs
- preview calls `PositionSizingEngine` and returns clipped weights
- confirm writes active holdings with Kelly-derived weight and stop metadata
- refresh updates current/highest price and writes snapshots
- refresh continues when one symbol price fetch fails

Router tests:

- Research page renders the Kelly simulator controls
- preview endpoint renders computed weights and cash reserve
- confirm endpoint writes holdings and returns success state
- refresh endpoint returns updated holdings and risk alerts

Integration tests:

- pipeline completion calls the shadow position refresh service with
  `refresh_source="pipeline"`
- stop-loss alerts are still produced by `StopLossMonitor.scan()`

## Explicit Non-Goals

- No scheduled background refresh.
- No live brokerage integration.
- No real order placement.
- No market depth, slippage, or commission simulation.
- No automatic YAML config edits.
- No automatic parameter optimization in the first version.

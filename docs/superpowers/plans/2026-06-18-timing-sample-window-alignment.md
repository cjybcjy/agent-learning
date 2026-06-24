# Timing Sample Window Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Timing confidence reflect the actual market-data sample window instead of using unreachable confidence tiers behind a 120-day fetch.

**Architecture:** Keep the existing Timing score formula, but align data acquisition and confidence reporting. The plugin will request a two-year lookback by default, expose `requested_days`, `sample_size`, and `confidence_tier` in `FactorScore.details`, and add partial-sample warnings when the fetcher returns less history than requested.

**Tech Stack:** Python, pytest, existing `TimingFactorPlugin` and `PriceFetcher` abstractions.

---

## Desired Behavior

- Default Timing fetch window becomes `520` trading days.
- Returned details include:
  - `requested_days`
  - `sample_size`
  - `confidence_tier`
- `< 60` bars still returns neutral score and confidence `0.0`.
- `60-79` bars remains low-confidence MA60-only mode.
- `80-249` bars remains medium-confidence short-sample mode.
- `250-499` bars is one-year quality.
- `>= 500` bars is two-year quality.
- When `sample_size < requested_days`, add a warning so the UI/report can show that Timing is based on partial data.

## Files

- Modify `sentinel/mgfs/plugins/timing.py`.
- Modify `tests/test_timing_edge_cases.py`.

## Tasks

### Task 1: Timing RED/GREEN

- [ ] Add a test fetcher that records the requested `days` argument.
- [ ] Add a test asserting Timing requests `520` days by default and returns `details["requested_days"] == 520`, `details["sample_size"]`, and `details["confidence_tier"]`.
- [ ] Add a test asserting partial 120-day history includes a partial-sample warning.
- [ ] Add a test asserting 260 bars produces `confidence == 0.75` and `confidence_tier == "one_year"`.
- [ ] Run `PYTHONPATH=. pytest tests/test_timing_edge_cases.py -q` and confirm RED.
- [ ] Implement constants and details/warnings in `TimingFactorPlugin`.
- [ ] Re-run `PYTHONPATH=. pytest tests/test_timing_edge_cases.py -q` and confirm GREEN.

### Task 2: Integration Check

- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_integration.py tests/test_mgfs_integration_module_a.py tests/test_mgfs_integration_module_b.py -q`.
- [ ] If any expectations depend on the old 120-day mock confidence, update them only when the new behavior is stricter and source-backed.

### Task 3: Verification

- [ ] Run `PYTHONPATH=. pytest tests/test_timing_edge_cases.py -q`.
- [ ] Run `PYTHONPATH=. pytest -q`.
- [ ] Restart `uvicorn` on port 8000.
- [ ] Smoke test `/api/eval/single`.

## Self-Review

- This plan does not change Timing score math.
- It makes confidence auditable from sample size.
- It prevents future users from reading Timing confidence without seeing the data window behind it.

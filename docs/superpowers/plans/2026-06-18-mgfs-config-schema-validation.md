# MGFS Config Schema Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail fast on malformed MGFS configuration so bad weights, rating gates, policy multipliers, or circuit breakers cannot silently shape investment decisions.

**Architecture:** Add a pure config validator with structured issues and a single exception type. Call it from `build_orchestrator()` before plugin loading so invalid YAML is rejected at the boundary. Keep validation conservative: validate critical fields and optional gate rules without adding an external schema dependency.

**Tech Stack:** Python dataclasses, pytest, existing YAML config loader.

---

## Validation Scope

- `modules`: enabled modules must have a string `class_path`.
- `scoring_formula`: each entry must be a mapping with numeric `weight >= 0`.
- `policy_multiplier`: each multiplier must be numeric and non-negative.
- `circuit_breakers`: enabled breakers must have non-empty string `rule`; `alert_level`, when provided, must be one of `hard_veto`, `soft_veto`, `yellow_warning`, `green_pass`.
- `rating_thresholds`: each threshold must have numeric `min_score`, string `label`, and string `action`.
- Optional rating gates:
  - `min_overall_confidence` must be `0..1`.
  - `required_factors.*.min_confidence` must be `0..1`.
  - `required_factors.*.min_score` must be numeric.
  - detail rules support `min`, `max`, `equals`, and `in`; `min/max` must be numeric and `in` must be a non-empty list.

## Files

- Create `sentinel/mgfs/config_validator.py`.
- Modify `sentinel/mgfs/config_loader.py`.
- Add `tests/test_mgfs_config_validator.py`.
- Modify `tests/test_mgfs_config_loader.py`.

## Tasks

### Task 1: Validator RED/GREEN

- [ ] Add tests for a valid config returning no issues.
- [ ] Add tests for invalid scoring weight, invalid circuit breaker alert level, and malformed Strong Buy gate.
- [ ] Add a test asserting `validate_mgfs_config(..., raise_on_error=True)` raises `MGFSConfigValidationError` with issue paths.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_config_validator.py -q` and confirm RED.
- [ ] Implement `ConfigValidationIssue`, `MGFSConfigValidationError`, and `validate_mgfs_config()`.
- [ ] Re-run `PYTHONPATH=. pytest tests/test_mgfs_config_validator.py -q` and confirm GREEN.

### Task 2: Loader RED/GREEN

- [ ] Add a config-loader test where `build_orchestrator()` rejects an invalid config before plugin construction.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_config_loader.py -q` and confirm RED.
- [ ] Import and call `validate_mgfs_config(config, raise_on_error=True)` at the start of `build_orchestrator()`.
- [ ] Re-run `PYTHONPATH=. pytest tests/test_mgfs_config_loader.py -q` and confirm GREEN.

### Task 3: Verification

- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_config_validator.py tests/test_mgfs_config_loader.py tests/test_mgfs_integration.py -q`.
- [ ] Run `PYTHONPATH=. pytest -q`.
- [ ] Restart `uvicorn` on port 8000.
- [ ] Smoke test `/api/eval/single`.

## Self-Review

- This plan rejects malformed config before runtime defaults hide the problem.
- It does not require exact weight sums, because current production config intentionally has zero-weight policy and inactive capacity.
- It validates gate semantics introduced by the previous Strong Buy work.

# Target Policy Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure all MGFS evaluation entry points use the same target metadata and ensure policy YAML multipliers participate in final scores.

**Architecture:** Add a small `TargetResolver` domain service that reads `moat_static_base.yaml` and fills `TargetInfo` metadata consistently. Update web single evaluation and pipeline loading to use it, then adjust `MGFSOrchestrator` so a `policy` factor's `details.multiplier` becomes the effective final multiplier when present.

**Tech Stack:** Python dataclasses, PyYAML, pytest, FastAPI service layer.

---

## Files

- Create `sentinel/mgfs/target_resolver.py`: resolves symbol metadata from moat YAML.
- Modify `sentinel/web/services/eval_service.py`: use `TargetResolver` before orchestrator evaluation.
- Modify `sentinel/web/services/pipeline_service.py`: load stock pool through `TargetResolver` so name/theme/role are preserved.
- Modify `sentinel/mgfs/orchestrator.py`: derive effective policy multiplier from the `policy` factor when present.
- Add `tests/test_mgfs_target_resolver.py`: resolver behavior.
- Modify `tests/test_pipeline_service.py`: stock pool metadata preservation.
- Modify `tests/test_web_eval_single.py`: single evaluation target metadata preservation.
- Modify `tests/test_mgfs_orchestrator.py`: policy factor multiplier behavior.

## Tasks

### Task 1: Target Resolver RED/GREEN

- [ ] Write tests proving a symbol-only evaluation is enriched with name, sector, theme, and ecosystem role from moat config.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_target_resolver.py -q` and confirm it fails because `TargetResolver` does not exist.
- [ ] Implement `TargetResolver.resolve()`.
- [ ] Re-run the resolver test and confirm it passes.

### Task 2: Entry Point Integration RED/GREEN

- [ ] Add tests showing `evaluate_single()` sends enriched `TargetInfo` to the orchestrator.
- [ ] Add tests showing `PipelineService._load_stock_pool()` preserves name, sector, theme, and ecosystem role.
- [ ] Run the focused tests and confirm failures.
- [ ] Update `eval_service.py` and `pipeline_service.py` to use `TargetResolver`.
- [ ] Re-run focused tests and confirm they pass.

### Task 3: Policy Multiplier RED/GREEN

- [ ] Add an orchestrator test where a `policy` factor returns `details.multiplier=1.2` and final score becomes `raw_total * 1.2`.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_orchestrator.py -q` and confirm the new test fails.
- [ ] Update `MGFSOrchestrator` to prefer policy factor multiplier over external policy rating fallback.
- [ ] Re-run orchestrator tests and confirm they pass.

### Task 4: Verification

- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_target_resolver.py tests/test_pipeline_service.py tests/test_web_eval_single.py tests/test_mgfs_orchestrator.py -q`.
- [ ] Run `PYTHONPATH=. pytest -q`.
- [ ] Restart `uvicorn` on port 8000 and smoke test `/dashboard/ops`.

## Self-Review

- Scope covers the first two ordered fixes only.
- Tests precede production changes.
- Existing manual policy fallback remains for compatibility when no `policy` factor is present.

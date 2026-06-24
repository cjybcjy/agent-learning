# Strong Buy Evidence Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent `Strong Buy` from being assigned by score alone; require explicit data sufficiency and factor-level evidence gates before the top rating is allowed.

**Architecture:** Add a pure rating-gate evaluator that understands optional `rating_thresholds.*` gate fields. Wire it into `MGFSOrchestrator` so high-score candidates with insufficient evidence fall through to the next lower threshold and expose the failed gate reasons in `report_sections`. Keep legacy thresholds without gates fully backward-compatible.

**Tech Stack:** Python dataclasses, pytest, existing YAML config loader.

---

## Ordered Systemization Roadmap

1. `Strong Buy` evidence gates: top rating needs score, confidence, valuation zone, and moat evidence coverage.
2. Low-confidence weight caps: stop dropped low-confidence modules from fully inflating remaining modules.
3. Timing sample-window alignment: make confidence thresholds reflect the actual amount of market data loaded.
4. Config schema validation: reject malformed thresholds, circuit breakers, and factor weights before runtime.

This plan implements item 1 only.

## Gate Shape

`rating_thresholds.strong_buy` may define optional gates:

```yaml
strong_buy:
  min_score: 90.0
  label: "Strong Buy"
  action: "重仓出击"
  min_overall_confidence: 0.8
  required_factors:
    moat:
      min_score: 80.0
      min_confidence: 0.8
      details:
        evidence_coverage: { min: 0.8 }
    valuation:
      min_confidence: 0.7
      details:
        zone: { in: ["strong_buy"] }
    timing:
      min_confidence: 0.5
```

Thresholds without these fields behave exactly as before.

## Files

- Create `sentinel/mgfs/rating_gates.py`: pure gate evaluator and failure dataclasses.
- Modify `sentinel/mgfs/orchestrator.py`: call the evaluator while classifying ratings and add `rating_gate_failures` to `report_sections`.
- Modify `config/mgfs_config.yaml`: add `Strong Buy` gates to production config.
- Add `tests/test_mgfs_rating_gates.py`: unit tests for gate evaluator.
- Modify `tests/test_mgfs_orchestrator.py`: integration tests for gated `Strong Buy` downgrade/pass.

## Tasks

### Task 1: Gate Evaluator RED/GREEN

- [ ] Write `tests/test_mgfs_rating_gates.py` with three behaviors:
  - thresholds without gates pass;
  - complete factor evidence passes;
  - missing/low factor evidence fails with readable reasons.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_rating_gates.py -q` and confirm RED because `sentinel.mgfs.rating_gates` does not exist.
- [ ] Create `sentinel/mgfs/rating_gates.py` with `RatingGateEvaluator`, `RatingGateFailure`, and `RatingGateResult`.
- [ ] Re-run `PYTHONPATH=. pytest tests/test_mgfs_rating_gates.py -q` and confirm GREEN.

### Task 2: Orchestrator Rating RED/GREEN

- [ ] Add a test where a 96 final score fails the `Strong Buy` gate because `moat.details.evidence_coverage` is too low and must fall through to `Accumulate`.
- [ ] Add a test where the same score passes all gates and remains `Strong Buy`.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_orchestrator.py -q` and confirm RED.
- [ ] Modify `MGFSOrchestrator.evaluate()` to call a gated rating classifier and persist failed gates in `report_sections["rating_gate_failures"]`.
- [ ] Re-run `PYTHONPATH=. pytest tests/test_mgfs_orchestrator.py -q` and confirm GREEN.

### Task 3: Production Config

- [ ] Add `min_overall_confidence` and `required_factors` to `config/mgfs_config.yaml` under `rating_thresholds.strong_buy`.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_config_loader.py tests/test_mgfs_integration.py -q` and confirm GREEN.

### Task 4: Verification

- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_rating_gates.py tests/test_mgfs_orchestrator.py tests/test_mgfs_config_loader.py -q`.
- [ ] Run `PYTHONPATH=. pytest -q`.
- [ ] Restart `uvicorn` on port 8000.
- [ ] Smoke test `/api/eval/single` with a symbol and confirm the response still renders a decision card.

## Self-Review

- Legacy thresholds without gate fields remain backward-compatible.
- Gate failures do not mutate factor scores; they only prevent top-rating upgrade.
- The strongest recommendation now has auditable prerequisites, reducing subjective override risk.

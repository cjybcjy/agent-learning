# Low Confidence Weight Caps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent low-confidence factor removal from inflating the remaining factors into an overconfident score.

**Architecture:** Replace full weight redistribution with a conservative confidence-adjusted weighting policy. Factors with `confidence < 0.5` contribute zero to the numerator, but their configured weight remains in the score denominator. System failures keep the same denominator behavior and are still downgraded by the existing failure circuit.

**Tech Stack:** Python, pytest, existing `MGFSOrchestrator`.

---

## Scoring Behavior

Current risky behavior:

- `moat=90`, weight `0.5`, confidence `0.9`
- `valuation=0`, weight `0.3`, confidence `0.0`
- Existing redistribution makes moat weight `1.0`, raw score `90.0`

New behavior:

- `moat` keeps numerator weight `0.5`
- `valuation` contributes numerator weight `0.0`
- Denominator remains configured present-factor weight `0.8`
- Raw score becomes `90 * 0.5 / 0.8 = 56.25`

This expresses “we have partial evidence”, not “the remaining evidence is complete”.

## Files

- Modify `sentinel/mgfs/orchestrator.py`: stop renormalizing low-confidence weights; compute raw score with configured denominator.
- Modify `tests/test_mgfs_orchestrator.py`: update redistribution tests to assert non-inflation and weight gap metadata.
- Modify `tests/test_orchestrator_system_failure.py`: keep failure expectation aligned with denominator-preserving scoring.

## Tasks

### Task 1: Orchestrator RED/GREEN

- [ ] Update `tests/test_mgfs_orchestrator.py::test_weight_redistributed_when_valuation_confidence_zero` to expect `adjusted_weights["moat"] == 0.5`, `valuation == 0.0`, `weight_denominator == 0.8`, and `raw_total == 56.25`.
- [ ] Update `tests/test_mgfs_orchestrator.py::test_weight_redistributed_proportionally` to expect original active weights, zero inactive weight, denominator `1.0`, and `raw_total == 50.0`.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_orchestrator.py -q` and confirm RED.
- [ ] Modify `MGFSOrchestrator._get_adjusted_weights()` and `_compute_raw_total()` so low-confidence weights are not redistributed.
- [ ] Add `weight_denominator` and `inactive_weight` to `report_sections`.
- [ ] Re-run `PYTHONPATH=. pytest tests/test_mgfs_orchestrator.py -q` and confirm GREEN.

### Task 2: System Failure Regression

- [ ] Run `PYTHONPATH=. pytest tests/test_orchestrator_system_failure.py -q`.
- [ ] If expectations differ only by safer denominator-preserving score, update comments/assertions without relaxing the core “not inflated” requirement.
- [ ] Re-run the test and confirm GREEN.

### Task 3: Verification

- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_orchestrator.py tests/test_orchestrator_system_failure.py -q`.
- [ ] Run `PYTHONPATH=. pytest -q`.
- [ ] Restart `uvicorn` on port 8000.
- [ ] Smoke test `/api/eval/single`.

## Self-Review

- This plan intentionally changes old redistribution semantics; tests should fail first.
- It makes missing/low-confidence evidence visible as a score discount, reducing subjective overreach.
- It preserves system-failure downgrade behavior.

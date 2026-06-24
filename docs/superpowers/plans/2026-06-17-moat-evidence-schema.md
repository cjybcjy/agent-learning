# Moat Evidence Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make subjective moat base scores auditable by introducing evidence-field checks and surfacing missing evidence in scoring details and the daily research agent.

**Architecture:** Add a pure domain auditor in `sentinel/mgfs/moat_evidence.py` that scans `companies.*.base_score.*` items for required evidence fields. Use that auditor in `MoatFactorPlugin` details/warnings and in `ResearchAgentService` suggestions without blocking existing YAML saves.

**Tech Stack:** Python dataclasses, PyYAML, pytest.

---

## Evidence Fields

Each moat base score dimension should eventually include:

- `source`: source name, filing, dataset, or research note reference.
- `as_of`: evidence date in `YYYY-MM-DD`.
- `confidence`: numeric evidence confidence between `0.0` and `1.0`.
- `bear_case`: a short counterargument or falsification condition.

`score` and `note` remain supported for backward compatibility.

## Files

- Create `sentinel/mgfs/moat_evidence.py`: evidence issue/report dataclasses and auditor.
- Modify `sentinel/mgfs/plugins/moat.py`: include evidence coverage in `FactorScore.details` and add warnings when fields are missing.
- Modify `sentinel/web/services/research_agent_service.py`: add a read-only suggestion when evidence coverage is incomplete.
- Add `tests/test_mgfs_moat_evidence.py`: auditor tests.
- Modify `tests/test_mgfs_moat_plugin.py`: plugin details/warnings tests.
- Modify `tests/test_research_agent_service.py`: Agent suggestion tests.

## Tasks

### Task 1: Auditor RED/GREEN

- [ ] Write tests for complete evidence, missing evidence, and invalid confidence/date.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_moat_evidence.py -q` and confirm RED.
- [ ] Implement `MoatEvidenceAuditor`.
- [ ] Re-run the auditor tests and confirm GREEN.

### Task 2: Moat Plugin RED/GREEN

- [ ] Add a test asserting `FactorScore.details["evidence_coverage"]` and missing-field warnings.
- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_moat_plugin.py -q` and confirm RED.
- [ ] Integrate `MoatEvidenceAuditor` into `MoatFactorPlugin`.
- [ ] Re-run moat plugin tests and confirm GREEN.

### Task 3: Agent RED/GREEN

- [ ] Add a test asserting Daily Research Agent emits `护城河评分缺少证据字段`.
- [ ] Run `PYTHONPATH=. pytest tests/test_research_agent_service.py -q` and confirm RED.
- [ ] Add the suggestion generator to `ResearchAgentService`.
- [ ] Re-run research agent tests and confirm GREEN.

### Task 4: Verification

- [ ] Run `PYTHONPATH=. pytest tests/test_mgfs_moat_evidence.py tests/test_mgfs_moat_plugin.py tests/test_research_agent_service.py -q`.
- [ ] Run `PYTHONPATH=. pytest -q`.
- [ ] Restart `uvicorn` on port 8000 and smoke test `/api/research-agent/run`.

## Self-Review

- This plan does not break legacy YAML.
- It makes subjective scores measurable through coverage and warnings.
- It prepares the next ordered step: Strong Buy data-sufficiency gates.

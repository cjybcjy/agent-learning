# Ops Config Schema Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Ops configuration console validate `mgfs_config.yaml` with the MGFS schema before save and show path-level errors in the UI.

**Architecture:** Keep YAML parsing and file allow-listing in `sentinel/web/services/config_service.py`, then route `mgfs_config.yaml` through `sentinel.mgfs.config_validator.validate_mgfs_config`. Preserve existing YAML and moat score checks for other files. Pass `filename` through the HTMX validate form so the backend can choose the correct validator.

**Tech Stack:** FastAPI, Jinja2 templates, HTMX, PyYAML, pytest, FastAPI TestClient.

---

### Task 1: API Validation Behavior

**Files:**
- Modify: `tests/test_web_config.py`
- Modify: `sentinel/web/services/config_service.py`
- Modify: `sentinel/web/routers/ops.py`
- Modify: `sentinel/web/templates/partials/config_editor.html`

- [ ] **Step 1: Write the failing route tests**

Add tests that load `mgfs_config.yaml`, validate invalid MGFS YAML with `filename=mgfs_config.yaml`, and reject saving invalid MGFS YAML before hot reload:

```python
def test_config_load_allows_mgfs_config():
    client = TestClient(create_app())
    response = client.get("/api/config/load/mgfs_config.yaml")
    assert response.status_code == 200
    assert "mgfs_config.yaml" in response.text


def test_config_validate_mgfs_config_reports_schema_paths():
    client = TestClient(create_app())
    response = client.post(
        "/api/config/validate",
        data={
            "filename": "mgfs_config.yaml",
            "content": "modules: {}\nscoring_formula:\n  moat:\n    weight: -0.2\n",
        },
    )
    assert response.status_code == 200
    assert "校验失败" in response.text
    assert "scoring_formula.moat.weight" in response.text


def test_config_save_mgfs_config_rejects_schema_errors():
    client = TestClient(create_app())
    response = client.post(
        "/api/config/save",
        data={
            "filename": "mgfs_config.yaml",
            "content": "modules: {}\nscoring_formula:\n  moat:\n    weight: -0.2\n",
        },
    )
    assert response.status_code == 200
    assert "校验失败" in response.text
    assert "scoring_formula.moat.weight" in response.text
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_web_config.py -q`

Expected: tests fail because `mgfs_config.yaml` is not allowed and `/api/config/validate` does not pass a filename to schema validation.

- [ ] **Step 3: Implement minimal backend behavior**

In `sentinel/web/services/config_service.py`:
- Add `mgfs_config.yaml` to `ALLOWED_FILES`.
- Change `validate_config(content: str)` to `validate_config(content: str, filename: str | None = None)`.
- When `filename == "mgfs_config.yaml"`, call `validate_mgfs_config(data)` and append messages as `"{issue.path}: {issue.message}"`.
- In `save_config`, call `validate_config(content, filename)`.

In `sentinel/web/routers/ops.py`, read `filename` from `/api/config/validate` form data and pass it to `validate_config`.

- [ ] **Step 4: Wire the validate form**

In `sentinel/web/templates/partials/config_editor.html`, make the precheck include both `filename` and `content` by leaving the hidden filename input inside the form and keeping `hx-include` scoped to the form controls.

- [ ] **Step 5: Run the focused test and confirm GREEN**

Run: `PYTHONPATH=. pytest tests/test_web_config.py -q`

Expected: all tests in `tests/test_web_config.py` pass.

---

### Task 2: Ops UI Discoverability

**Files:**
- Modify: `tests/test_web_workstation_ui.py`
- Modify: `sentinel/web/templates/ops.html`
- Modify: `sentinel/web/templates/partials/config_status.html`

- [ ] **Step 1: Write the failing UI test**

Add assertions that the Ops page exposes a `mgfs_config.yaml` button and that the status template can show schema path details:

```python
assert "评分总配置" in response.text
assert 'hx-get="/api/config/load/mgfs_config.yaml"' in response.text
assert "保存前会先执行 YAML 与 MGFS Schema 校验" in response.text
```

- [ ] **Step 2: Run the UI test and confirm RED**

Run: `PYTHONPATH=. pytest tests/test_web_workstation_ui.py -q`

Expected: fails because the button and schema helper text are not yet rendered.

- [ ] **Step 3: Implement minimal UI changes**

In `sentinel/web/templates/ops.html`, add a button labeled `评分总配置` that loads `/api/config/load/mgfs_config.yaml`, and add compact helper text near the config console explaining save-precheck behavior.

In `sentinel/web/templates/partials/config_status.html`, keep the existing green/red result layout and make the failure heading clear as `Schema 校验失败` while preserving YAML error display.

- [ ] **Step 4: Run UI tests and confirm GREEN**

Run: `PYTHONPATH=. pytest tests/test_web_workstation_ui.py -q`

Expected: all Ops/workstation UI tests pass.

---

### Task 3: Verification

**Files:**
- Verify: `tests/test_web_config.py`
- Verify: `tests/test_web_workstation_ui.py`
- Verify: browser route `http://127.0.0.1:8000/dashboard/ops`

- [ ] **Step 1: Run focused backend and UI tests**

Run: `PYTHONPATH=. pytest tests/test_web_config.py tests/test_web_workstation_ui.py -q`

Expected: all focused tests pass.

- [ ] **Step 2: Run broader regression tests**

Run: `PYTHONPATH=. pytest tests/test_mgfs_config_validator.py tests/test_mgfs_config_loader.py tests/test_web_config.py tests/test_web_workstation_ui.py -q`

Expected: all selected regression tests pass.

- [ ] **Step 3: Run formatting sanity check**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Validate rendered frontend**

Use Playwright because the Browser plugin is not available in this session. Load `http://127.0.0.1:8000/dashboard/ops`, verify the page is not blank, click `评分总配置`, replace the textarea with invalid YAML containing `weight: -0.2`, click `预校验`, and confirm the visible result includes `scoring_formula.moat.weight`.

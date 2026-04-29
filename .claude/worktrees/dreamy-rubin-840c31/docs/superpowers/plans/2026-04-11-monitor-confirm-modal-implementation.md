# Monitor Confirm Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the shared app confirm modal so the scheduler start flow uses a warm light checkbox form while existing confirm callers keep their current boolean behavior.

**Architecture:** Keep all changes inside `monitor_web/index.html` except for one focused regression test file. Preserve `showAppConfirm()` as the shared boolean confirm API, add `showAppConfirmWithCheckbox()` as a thin wrapper over the same modal lifecycle, and scope all warm-light visual changes under `#modalAppConfirm` so no other modal inherits the new styling.

**Tech Stack:** Vanilla HTML/CSS/JavaScript in `monitor_web/index.html`, pytest string/regression tests in `tests/`

---

## File Responsibilities

- **Modify:** `monitor_web/index.html:1300-1322` — app-confirm-only warm-light styles, checkbox row styles, confirm tone styles, focus states.
- **Modify:** `monitor_web/index.html:3025-3039` — add hidden checkbox markup inside `#modalAppConfirm`.
- **Modify:** `monitor_web/index.html:4196-4250` — keep `showAppConfirm()` boolean, add checkbox wrapper/reset logic, preserve pending-confirm cancel semantics.
- **Modify:** `monitor_web/index.html:4490-4527` — replace native `confirm()` in `toggleScheduler()` with the checkbox wrapper.
- **Create:** `tests/test_scheduler_confirm_modal_ui.py` — focused regression tests for the modal DOM, scoped styles, wrapper function, and scheduler start flow.

## Verification Strategy

Use offline string/regression tests because the repo already validates `monitor_web/index.html` this way (`tests/test_batch_download_webui_modal.py:1-20`, `tests/test_batch_failure_state_ui.py:1-18`). Final verification should run the new targeted test file plus the existing modal-related regressions.

---

### Task 1: Add failing regression tests for the confirm modal contract

**Files:**
- Create: `tests/test_scheduler_confirm_modal_ui.py`
- Test: `tests/test_scheduler_confirm_modal_ui.py`

- [ ] **Step 1: Write the failing test file**

```python
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_app_confirm_modal_exposes_checkbox_markup_and_scoped_styles():
    html = _html()
    assert 'id="appConfirmCheckboxRow"' in html
    assert 'id="appConfirmCheckbox"' in html
    assert 'id="appConfirmCheckboxLabel"' in html
    assert 'id="appConfirmCheckboxHint"' in html
    assert '#modalAppConfirm > .modal' in html
    assert '#modalAppConfirm .modal-confirm-checkbox-row' in html
    assert re.search(r"#modalAppConfirm \.modal-confirm-checkbox input \{[\s\S]*?display:\s*block;", html)
    assert '#modalAppConfirm .modal-confirm-checkbox input:focus-visible + .checkbox-box' in html
    assert '#modalAppConfirm .btn-ghost' in html


def test_app_confirm_checkbox_wrapper_preserves_boolean_base_confirm():
    html = _html()
    assert 'function showAppConfirmWithCheckbox(' in html
    assert 'function showAppConfirm(options)' in html
    assert 'let _appConfirmGeneration = 0;' in html
    assert 'if (_appConfirmGeneration === generation)' in html
    assert 'return confirmed ? { confirmed: true, checked } : { confirmed: false };' in html


def test_toggle_scheduler_uses_checkbox_modal_and_not_native_confirm():
    html = _html()
    match = re.search(r"async function toggleScheduler\(\) \{([\s\S]*?)\n  \}", html)
    assert match, "toggleScheduler() should exist"
    body = match.group(1)
    assert 'showAppConfirmWithCheckbox({' in body
    assert 'confirm(' not in body
    assert 'auto_download: confirmResult.checked' in body
    assert 'if (!confirmResult.confirmed) return;' in body
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py -q
```

Expected: FAIL because the checkbox row, wrapper function, and `toggleScheduler()` integration do not exist yet.

- [ ] **Step 3: Commit the red test file only after you confirm it fails locally**

```bash
git add tests/test_scheduler_confirm_modal_ui.py
git commit -m "test: lock scheduler confirm modal contract"
```

Expected: If you keep strict TDD, this commit may be skipped until the first green slice. If your local policy forbids red commits, stage the file now and include it in Task 2’s commit instead.

---

### Task 2: Add scoped checkbox markup and warm-light modal styling

**Files:**
- Modify: `monitor_web/index.html:1300-1322`
- Modify: `monitor_web/index.html:3025-3039`
- Test: `tests/test_scheduler_confirm_modal_ui.py::test_app_confirm_modal_exposes_checkbox_markup_and_scoped_styles`

- [ ] **Step 1: Insert the checkbox markup into `#modalAppConfirm`**

Replace the current body block with:

```html
<div class="modal-body" style="padding-top:12px">
  <p class="modal-confirm-desc" id="appConfirmBody"></p>
  <div class="modal-confirm-checkbox-row" id="appConfirmCheckboxRow" hidden>
    <label class="checkbox-label modal-confirm-checkbox">
      <input type="checkbox" id="appConfirmCheckbox">
      <span class="checkbox-box"></span>
      <span id="appConfirmCheckboxLabel"></span>
    </label>
    <div class="form-hint modal-confirm-checkbox-hint" id="appConfirmCheckboxHint"></div>
  </div>
</div>
```

- [ ] **Step 2: Add app-confirm-only warm-light styles**

Add scoped rules under the existing `#modalAppConfirm` style block:

```css
#modalAppConfirm > .modal {
  background: #faf9f5;
  border: 1px solid #e8e6dc;
  box-shadow: rgba(0,0,0,0.08) 0 8px 28px, 0 0 0 1px #f0eee6;
}
#modalAppConfirm .modal-header {
  border-bottom-color: #e8e6dc;
}
#modalAppConfirm .modal-title {
  color: #141413;
}
#modalAppConfirm .modal-close {
  background: #f5f4ed;
  border-color: #e8e6dc;
  color: #5e5d59;
}
#modalAppConfirm .modal-close:hover {
  background: #e8e6dc;
  color: #141413;
}
#modalAppConfirm .modal-confirm-desc {
  color: #5e5d59;
}
#modalAppConfirm .modal-confirm-checkbox-row {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e8e6dc;
}
#modalAppConfirm .modal-confirm-checkbox {
  align-items: flex-start;
  color: #4d4c48;
}
#modalAppConfirm .modal-confirm-checkbox input {
  display: block;
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  border: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
}
#modalAppConfirm .modal-confirm-checkbox input:focus-visible + .checkbox-box,
#modalAppConfirm .modal-confirm-checkbox:focus-within .checkbox-box {
  outline: 2px solid #3898ec;
  outline-offset: 2px;
}
#modalAppConfirm .checkbox-box {
  border-color: #b0aea5;
}
#modalAppConfirm .checkbox-label input:checked + .checkbox-box {
  background: var(--success);
  border-color: var(--success);
}
#modalAppConfirm .modal-confirm-checkbox-hint {
  margin-top: 8px;
  margin-left: 26px;
  color: #87867f;
}
#modalAppConfirm .btn-ghost {
  background: #e8e6dc;
  border: 1px solid #d1cfc5;
  color: #4d4c48;
}
#modalAppConfirm .btn-ghost:hover {
  background: #d1cfc5;
  color: #141413;
}
#modalAppConfirm .btn-success {
  background: var(--success);
  color: #fff;
}
```

Also add one regression assertion to the test file:

```python
assert '#modalAppConfirm .modal-confirm-checkbox input:focus-visible + .checkbox-box' in html
```

Do **not** edit global `.modal`, `.modal-header`, `.btn-ghost`, or shared button selectors outside `#modalAppConfirm`.

- [ ] **Step 3: Run the first targeted test to verify the markup/styles pass**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py::test_app_confirm_modal_exposes_checkbox_markup_and_scoped_styles -q
```

Expected: PASS.

- [ ] **Step 4: Commit the markup/style slice**

```bash
git add monitor_web/index.html tests/test_scheduler_confirm_modal_ui.py
git commit -m "feat: add scoped scheduler confirm modal styling"
```

---

### Task 3: Add the checkbox wrapper while preserving the boolean confirm API

**Files:**
- Modify: `monitor_web/index.html:4196-4250`
- Test: `tests/test_scheduler_confirm_modal_ui.py::test_app_confirm_checkbox_wrapper_preserves_boolean_base_confirm`

- [ ] **Step 1: Run the wrapper test to verify it fails**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py::test_app_confirm_checkbox_wrapper_preserves_boolean_base_confirm -q
```

Expected: FAIL because `showAppConfirmWithCheckbox()` is missing.

- [ ] **Step 2: Add a generation counter and one reset helper near the existing app confirm logic**

Add a generation counter plus reset helper before `showAppConfirm()`:

```js
let _appConfirmGeneration = 0;

function resetAppConfirmCheckbox() {
  const row = document.getElementById('appConfirmCheckboxRow');
  const checkbox = document.getElementById('appConfirmCheckbox');
  const label = document.getElementById('appConfirmCheckboxLabel');
  const hint = document.getElementById('appConfirmCheckboxHint');
  if (row) row.hidden = true;
  if (checkbox) checkbox.checked = false;
  if (label) label.textContent = '';
  if (hint) {
    hint.textContent = '';
    hint.hidden = true;
  }
}
```

- [ ] **Step 3: Keep `showAppConfirm()` boolean-only and add confirm tone support**

Update `showAppConfirm()` so existing callers still resolve `true/false`, but it accepts `confirmTone`:

```js
function showAppConfirm(options) {
  return new Promise((resolve) => {
    _appConfirmGeneration += 1;
    if (_appConfirmResolve) {
      const prev = _appConfirmResolve;
      _appConfirmResolve = null;
      prev(false);
    }
    _appConfirmResolve = resolve;

    const primaryBtn = document.getElementById('appConfirmPrimaryBtn');
    const tone = options.confirmTone || (options.variant === 'danger' ? 'danger' : 'primary');
    primaryBtn.className = 'btn ' + (tone === 'danger'
      ? 'btn-danger'
      : tone === 'success'
        ? 'btn-success'
        : 'btn-primary');

    resetAppConfirmCheckbox();
    // ...existing title/body/cancel wiring stays here...
  });
}
```

- [ ] **Step 4: Add the checkbox wrapper and preserve close semantics**

Add the wrapper and guard post-await cleanup so an older cancelled wrapper cannot wipe a newer confirm:

```js
async function showAppConfirmWithCheckbox(options) {
  const confirmPromise = showAppConfirm(options);
  const generation = _appConfirmGeneration;
  const row = document.getElementById('appConfirmCheckboxRow');
  const checkbox = document.getElementById('appConfirmCheckbox');
  const label = document.getElementById('appConfirmCheckboxLabel');
  const hint = document.getElementById('appConfirmCheckboxHint');

  row.hidden = false;
  checkbox.checked = options.checkbox.checked !== false;
  label.textContent = options.checkbox.label || '';
  hint.textContent = options.checkbox.description || '';
  hint.hidden = !options.checkbox.description;

  const confirmed = await confirmPromise;
  const checked = checkbox.checked;
  if (_appConfirmGeneration === generation) {
    resetAppConfirmCheckbox();
  }
  return confirmed ? { confirmed: true, checked } : { confirmed: false };
}
```

Then adjust `closeAppConfirm()` so it still:
- removes the Esc handler
- clears the `modal-app-confirm--danger` class
- closes the modal
- preserves the “new confirm cancels previous confirm” behavior already used at `monitor_web/index.html:4198-4202`

If `resetAppConfirmCheckbox()` is called from `closeAppConfirm()`, capture `checkbox.checked` before resetting.

- [ ] **Step 5: Run the wrapper test to verify it passes**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py::test_app_confirm_checkbox_wrapper_preserves_boolean_base_confirm -q
```

Expected: PASS.

- [ ] **Step 6: Commit the JS wrapper slice**

```bash
git add monitor_web/index.html tests/test_scheduler_confirm_modal_ui.py
git commit -m "feat: add checkbox wrapper for app confirm modal"
```

---

### Task 4: Replace the native scheduler confirm flow

**Files:**
- Modify: `monitor_web/index.html:4490-4527`
- Test: `tests/test_scheduler_confirm_modal_ui.py::test_toggle_scheduler_uses_checkbox_modal_and_not_native_confirm`

- [ ] **Step 1: Run the scheduler-flow test to verify it fails**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py::test_toggle_scheduler_uses_checkbox_modal_and_not_native_confirm -q
```

Expected: FAIL because `toggleScheduler()` still uses native `confirm()`.

- [ ] **Step 2: Replace the native `confirm()` block with the checkbox wrapper call**

Change the start branch in `toggleScheduler()` to:

```js
const confirmResult = await showAppConfirmWithCheckbox({
  title: '启动监控',
  message: '开始按计划扫描账号更新。',
  confirmText: '启动监控',
  cancelText: '取消',
  confirmTone: 'success',
  checkbox: {
    label: '扫描到新视频后自动下载',
    description: '每轮扫描完成后自动开始下载，最多 2 个视频同时下载。',
    checked: true,
  },
});
if (!confirmResult.confirmed) return;

const r = await api('POST', '/scheduler/start', {
  auto_download: confirmResult.checked,
});
```

Also update the success toast to use `confirmResult.checked`.

- [ ] **Step 3: Run the scheduler-flow test to verify it passes**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py::test_toggle_scheduler_uses_checkbox_modal_and_not_native_confirm -q
```

Expected: PASS.

- [ ] **Step 4: Commit the scheduler integration slice**

```bash
git add monitor_web/index.html tests/test_scheduler_confirm_modal_ui.py
git commit -m "feat: replace native scheduler confirm with app modal"
```

---

### Task 5: Run regression verification before handoff

**Files:**
- Modify: none expected
- Test: `tests/test_scheduler_confirm_modal_ui.py`
- Test: `tests/test_batch_download_webui_modal.py`
- Test: `tests/test_batch_failure_state_ui.py`

- [ ] **Step 1: Run the focused frontend regression suite**

Run:
```bash
python -m pytest tests/test_scheduler_confirm_modal_ui.py tests/test_batch_download_webui_modal.py tests/test_batch_failure_state_ui.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff on the new Python test file**

Run:
```bash
python -m ruff check tests/test_scheduler_confirm_modal_ui.py
```

Expected: PASS with no output.

- [ ] **Step 3: Inspect the final diff before handoff**

Run:
```bash
git diff -- monitor_web/index.html tests/test_scheduler_confirm_modal_ui.py
```

Expected: only the scoped modal/test changes described in the spec.

- [ ] **Step 4: Commit the final verification touch-up if anything changed during cleanup**

```bash
git add monitor_web/index.html tests/test_scheduler_confirm_modal_ui.py
git commit -m "test: verify scheduler confirm modal regressions"
```

If no files changed after verification, skip the commit and document that verification passed with no diff.

---

## Handoff Notes

- Keep the implementation inside the existing single-file frontend pattern used by this repo; do not split out new JS/CSS files for this feature.
- Do not change any non-`#modalAppConfirm` modal styling.
- Do not change the boolean call contract of existing `showAppConfirm()` callers.
- Prefer the existing checkbox markup pattern already used by `modalScanConfirm` so the UI stays internally consistent.
- Before claiming completion, run `@superpowers:verification-before-completion`.

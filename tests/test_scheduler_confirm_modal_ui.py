"""Tests for the scheduler confirm modal UI.

Phase 4 模块化后：
- 弹窗 HTML → templates/modals/modal-confirm.html
- 弹窗样式 → static/css/theme.css
- JS 逻辑 → modules/ui.js, components/scheduler-panel.js
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"
TEMPLATE_FILE = ROOT / "monitor_web" / "templates" / "modals" / "modal-confirm.html"
CSS_FILE = ROOT / "monitor_web" / "static" / "css" / "theme.css"
UI_JS = ROOT / "monitor_web" / "js" / "modules" / "ui.js"
SCHEDULER_PANEL = ROOT / "monitor_web" / "js" / "components" / "scheduler-panel.js"


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _tpl() -> str:
    return TEMPLATE_FILE.read_text(encoding="utf-8")


def _css() -> str:
    return CSS_FILE.read_text(encoding="utf-8")


def _ui_js() -> str:
    return UI_JS.read_text(encoding="utf-8")


def _scheduler_panel() -> str:
    return SCHEDULER_PANEL.read_text(encoding="utf-8")


def test_app_confirm_modal_exposes_checkbox_markup_and_scoped_styles():
    """checkbox 标记在模板文件，样式在 theme.css（已提取）。"""
    tpl = _tpl()
    css = _css()
    for expected_id in [
        'id="appConfirmCheckboxRow"',
        'id="appConfirmCheckbox"',
        'id="appConfirmCheckboxLabel"',
        'id="appConfirmCheckboxHint"',
    ]:
        assert expected_id in tpl, f"{expected_id} 应在模板文件中"

    for selector in [
        '#modalAppConfirm > .modal',
        '#modalAppConfirm .modal-confirm-checkbox-row',
        '#modalAppConfirm .modal-confirm-checkbox input:focus-visible + .checkbox-box',
        '#modalAppConfirm .btn-ghost',
    ]:
        assert selector in css, f"{selector} 应在 theme.css 中"


def test_app_confirm_checkbox_wrapper_exposes_contract_level_api():
    """JS API 逻辑在 modules/ui.js。"""
    ui_js = _ui_js()

    assert 'options.confirmTone' in ui_js
    assert "tone === 'success' ? 'btn-success'" in ui_js
    assert 'setAppConfirmGeneration(' in ui_js
    assert 'resetAppConfirmCheckbox();' in ui_js
    assert 'function resetAppConfirmCheckbox()' in ui_js
    assert "if (row) row.hidden = true;" in ui_js
    assert "if (checkbox) checkbox.checked = false;" in ui_js
    assert "if (label) label.textContent = '';" in ui_js
    # Check for hint.textContent = ''; pattern (whitespace flexible)
    assert "hint.textContent = ''" in ui_js
    assert 'function showAppConfirmWithCheckbox(' in ui_js
    assert 'function showAppConfirm(' in ui_js

    wrapper_start = ui_js.index('function showAppConfirmWithCheckbox(')
    wrapper_end = ui_js.index('function _resetScanNowState', wrapper_start)
    wrapper_body = ui_js[wrapper_start:wrapper_end]
    return_idx = wrapper_body.rfind('return')
    assert return_idx != -1
    return_tail = wrapper_body[return_idx:]
    assert 'confirmed' in return_tail
    assert 'checked' in return_tail


def test_toggle_scheduler_uses_checkbox_modal_wrapper_instead_of_native_confirm():
    scheduler_panel = _scheduler_panel()

    assert 'showAppConfirmWithCheckbox(' in scheduler_panel
    assert 'confirm(' not in scheduler_panel

    for expected in ['auto_download', 'checked']:
        assert expected in scheduler_panel

    wrapper_index = scheduler_panel.index('showAppConfirmWithCheckbox(')
    start_call_index = scheduler_panel.find('/scheduler/start', wrapper_index)
    return_index = scheduler_panel.find('return', wrapper_index)
    assert start_call_index != -1
    assert return_index != -1
    assert wrapper_index < return_index < start_call_index

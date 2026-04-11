import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"


def test_app_confirm_modal_exposes_checkbox_markup_and_scoped_styles():
    html = INDEX_HTML.read_text(encoding="utf-8")

    for expected in [
        'id="appConfirmCheckboxRow"',
        'id="appConfirmCheckbox"',
        'id="appConfirmCheckboxLabel"',
        'id="appConfirmCheckboxHint"',
        '#modalAppConfirm > .modal',
        '#modalAppConfirm .modal-confirm-checkbox-row',
        '#modalAppConfirm .modal-confirm-checkbox input:focus-visible + .checkbox-box',
        '#modalAppConfirm .btn-ghost',
    ]:
        assert expected in html

    assert re.search(
        r"#modalAppConfirm \.modal-confirm-checkbox input \{[\s\S]*?display:\s*block;",
        html,
    )


def test_app_confirm_checkbox_wrapper_exposes_contract_level_api():
    html = INDEX_HTML.read_text(encoding="utf-8")

    # confirmTone option support in showAppConfirm
    assert 'options.confirmTone' in html
    assert "tone === 'success' ? 'btn-success'" in html
    # generation counter incremented at top of showAppConfirm Promise body
    assert '_appConfirmGeneration += 1;' in html
    # reset helper called inside showAppConfirm
    assert 'resetAppConfirmCheckbox();' in html
    # reset helper defined with all checkbox elements
    assert 'function resetAppConfirmCheckbox()' in html
    assert "if (row) row.hidden = true;" in html
    assert "if (checkbox) checkbox.checked = false;" in html
    assert "if (label) label.textContent = '';" in html
    assert "if (hint) {\n      hint.textContent = '';\n      hint.hidden = true;" in html or \
           "if (hint) {\n      hint.textContent = '';" in html
    # wrapper exists and returns contract shape
    assert 'function showAppConfirmWithCheckbox(' in html
    assert 'function showAppConfirm(' in html

    wrapper_start = html.index('function showAppConfirmWithCheckbox(')
    wrapper_end = html.index('function _resetScanNowState', wrapper_start)
    wrapper_body = html[wrapper_start:wrapper_end]
    return_idx = wrapper_body.rfind('return')
    assert return_idx != -1
    return_tail = wrapper_body[return_idx:]
    assert 'confirmed' in return_tail
    assert 'checked' in return_tail


def test_toggle_scheduler_uses_checkbox_modal_wrapper_instead_of_native_confirm():
    html = INDEX_HTML.read_text(encoding="utf-8")
    scheduler_start = html.index('async function toggleScheduler()')
    scheduler_end = html.find('async function reloadJobs()', scheduler_start)
    assert scheduler_end != -1
    scheduler_slice = html[scheduler_start:scheduler_end]

    assert 'showAppConfirmWithCheckbox(' in scheduler_slice
    assert 'confirm(' not in scheduler_slice

    for expected in ['auto_download', 'checked']:
        assert expected in scheduler_slice

    wrapper_index = scheduler_slice.index('showAppConfirmWithCheckbox(')
    start_call_index = scheduler_slice.find('/scheduler/start', wrapper_index)
    return_index = scheduler_slice.find('return', wrapper_index)
    assert start_call_index != -1
    assert return_index != -1
    assert wrapper_index < return_index < start_call_index

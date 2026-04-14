"""
Regression: scanNow used to assign to imported _pendingScanNow / _scanNowSubmitting.

In ES modules, imported bindings from another module are not assignable in the
consumer (throws TypeError: Assignment to constant variable). Updates must go
through setPendingScanNow / setScanNowSubmitting in state.js (see ui._resetScanNowState).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_JS = ROOT / "monitor_web" / "js" / "modules" / "accounts.js"


def test_accounts_js_scan_now_does_not_assign_to_imported_state_bindings():
    text = ACCOUNTS_JS.read_text(encoding="utf-8")
    # Disallow direct reassignment of these imported names (must use setters from state.js).
    assert "_pendingScanNow =" not in text
    assert "_scanNowSubmitting =" not in text


def test_accounts_js_imports_state_setters_for_scan_now():
    text = ACCOUNTS_JS.read_text(encoding="utf-8")
    assert "setPendingScanNow" in text
    assert "setScanNowSubmitting" in text

"""
Regression test: clicking "取消" in the scheduler confirm modal should fully
restore the toggle button (text, class, onclick handler) so the button is
clickable again.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_PANEL = ROOT / "monitor_web" / "js" / "components" / "scheduler-panel.js"
UI_JS = ROOT / "monitor_web" / "js" / "modules" / "ui.js"


def _scheduler() -> str:
    return SCHEDULER_PANEL.read_text(encoding="utf-8")


def _ui() -> str:
    return UI_JS.read_text(encoding="utf-8")


def test_cancel_restores_toggle_button_properly():
    """
    After `if (!confirmResult.confirmed) return;` in toggleScheduler,
    the finally block must restore the button completely before the
    function returns.

    Verification:
    1. toggleScheduler must have a finally block
    2. The finally block must reset pointerEvents and innerHTML
    3. The finally block must call updateSchedulerUI after innerHTML reset
    """
    js = _scheduler()

    ts_start = js.index("export async function toggleScheduler()")
    ts_end = js.index("\nexport", ts_start + 1)
    ts_body = js[ts_start:ts_end]

    # toggleScheduler must have a finally block (not just trailing statements)
    assert "} finally {" in ts_body, (
        "toggleScheduler must have a finally block to restore button on cancel"
    )

    # Extract finally block content
    finally_idx = ts_body.rindex("} finally {")
    # Find the matching closing brace for finally
    brace_count = 1
    i = finally_idx + len("} finally {")
    while brace_count > 0:
        if ts_body[i] == '{':
            brace_count += 1
        elif ts_body[i] == '}':
            brace_count -= 1
        i += 1
    finally_content = ts_body[finally_idx:i]

    # finally must reset pointerEvents
    assert "btn.style.pointerEvents = ''" in finally_content, (
        "finally must reset pointerEvents"
    )

    # finally must reset innerHTML (not leave spinner hanging)
    assert "btn.innerHTML = ''" in finally_content, (
        "finally must reset innerHTML"
    )

    # innerHTML = '' must come before updateSchedulerUI() in finally
    ih_idx = finally_content.index("btn.innerHTML = ''")
    usi_idx = finally_content.index("updateSchedulerUI()")
    assert ih_idx < usi_idx, (
        "btn.innerHTML = '' must come BEFORE updateSchedulerUI() in finally"
    )


def test_updateSchedulerUI_restores_stopped_state_unconditionally():
    """
    updateSchedulerUI() must unconditionally restore the button text,
    class, and onclick for the stopped (schedulerRunning=false) branch,
    so it properly repairs the button after a cancelled confirm.
    """
    js = _ui()

    usi_start = js.index("export function updateSchedulerUI()")
    # Find end: next export or comment block (modal click-outside handler)
    next_export = js.find("\nexport ", usi_start + 1)
    next_comment = js.find("\n// ── ", usi_start + 1)
    candidates = [x for x in [next_export, next_comment] if x != -1]
    usi_end = min(candidates) if candidates else len(js)
    usi_body = js[usi_start:usi_end]

    # stopped branch must set textContent (not rely on leftover innerHTML)
    assert "btn.textContent" in usi_body, (
        "updateSchedulerUI must set btn.textContent for stopped state"
    )

    # stopped branch must reset className to btn-success
    assert "btn.className = 'btn btn-success'" in usi_body, (
        "updateSchedulerUI must reset className to btn-success in stopped state"
    )

    # stopped branch must reassign onclick
    assert "btn.onclick = toggleScheduler" in usi_body, (
        "updateSchedulerUI must reassign onclick in stopped state"
    )

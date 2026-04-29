"""
Regression: scheduler-panel must not assign to imported schedulerRunning.

ES module imports are read-only in the consumer; assignment throws and toggleScheduler
catch shows a misleading「网络错误」.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "monitor_web" / "js" / "components" / "scheduler-panel.js"


def test_scheduler_panel_does_not_assign_to_imported_scheduler_running():
    text = PANEL.read_text(encoding="utf-8")
    assert "schedulerRunning =" not in text


def test_ui_exports_set_scheduler_running():
    ui = ROOT / "monitor_web" / "js" / "modules" / "ui.js"
    t = ui.read_text(encoding="utf-8")
    assert "export function setSchedulerRunning" in t
    assert "setSchedulerRunning(data && data.running)" in t

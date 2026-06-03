"""Regression tests for pywebview desktop close choices."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from monitor_ui_desktop_close import (
    DesktopCloseController,
    get_tray_text,
    load_close_preference,
    save_close_preference,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeWindow:
    def __init__(self) -> None:
        self.evaluated: list[str] = []
        self.evaluate_result = True
        self.evaluate_results: list[bool] = []
        self.evaluate_error: Exception | None = None
        self.hidden = False
        self.minimized = False
        self.destroyed = False
        self.shown = False
        self.restored = False

    def evaluate_js(self, script: str) -> bool:
        if self.evaluate_error is not None:
            raise self.evaluate_error
        self.evaluated.append(script)
        if self.evaluate_results:
            return self.evaluate_results.pop(0)
        return self.evaluate_result

    def hide(self) -> None:
        self.hidden = True

    def minimize(self) -> None:
        self.minimized = True

    def destroy(self) -> None:
        self.destroyed = True

    def show(self) -> None:
        self.shown = True

    def restore(self) -> None:
        self.restored = True


class FakeTrayThing:
    def __init__(self) -> None:
        self.Text = ""
        self.BalloonTipTitle = ""
        self.BalloonTipText = ""


def test_close_preference_round_trips(tmp_path):
    path = tmp_path / "desktop-close.json"

    save_close_preference("tray", path)

    assert load_close_preference(path) == "tray"
    assert json.loads(path.read_text(encoding="utf-8")) == {"action": "tray"}


def test_close_preference_ignores_invalid_json(tmp_path):
    path = tmp_path / "desktop-close.json"
    path.write_text('{"action": "unsupported"}', encoding="utf-8")

    assert load_close_preference(path) is None


def test_native_close_without_preference_opens_vue_dialog(tmp_path):
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)

    result = controller.handle_window_closing()

    assert result is False
    assert len(window.evaluated) == 1
    assert "__YTDLP_DESKTOP_CLOSE_READY__" in window.evaluated[0]
    assert "window.pywebview.api.closeWithChoice" in window.evaluated[0]
    assert "desktop-close-request" in window.evaluated[0]
    assert not window.destroyed


def test_native_close_queues_dialog_when_vue_bridge_is_not_ready(tmp_path):
    window = FakeWindow()
    window.evaluate_results = [False, True]
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)

    result = controller.handle_window_closing()

    assert result is False
    assert len(window.evaluated) == 2
    assert "__YTDLP_DESKTOP_CLOSE_READY__" in window.evaluated[0]
    assert "__YTDLP_PENDING_DESKTOP_CLOSE__" in window.evaluated[1]
    assert not window.destroyed


def test_second_native_close_after_pending_queue_allows_close(tmp_path):
    window = FakeWindow()
    window.evaluate_results = [False, True, False]
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)

    first_result = controller.handle_window_closing()
    second_result = controller.handle_window_closing()

    assert first_result is False
    assert second_result is True
    assert len(window.evaluated) == 3
    assert "__YTDLP_PENDING_DESKTOP_CLOSE__" in window.evaluated[1]
    assert "__YTDLP_PENDING_DESKTOP_CLOSE__" not in window.evaluated[2]
    assert not window.destroyed


def test_native_close_allows_close_when_dialog_cannot_show_or_queue(tmp_path):
    window = FakeWindow()
    window.evaluate_results = [False, False]
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)

    result = controller.handle_window_closing()

    assert result is True
    assert len(window.evaluated) == 2
    assert not window.destroyed


def test_native_close_allows_close_when_dialog_dispatch_fails(tmp_path):
    window = FakeWindow()
    window.evaluate_error = RuntimeError("renderer unavailable")
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)

    result = controller.handle_window_closing()

    assert result is True
    assert not window.destroyed


def test_remembered_tray_choice_cancels_close_and_hides_window(tmp_path):
    path = tmp_path / "desktop-close.json"
    save_close_preference("tray", path)
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=path)
    controller.bind_window(window)
    controller._ensure_tray_icon = lambda: True  # type: ignore[method-assign]

    result = controller.handle_window_closing()

    assert result is False
    assert window.hidden
    assert not window.destroyed


def test_remembered_quit_choice_allows_native_close(tmp_path):
    path = tmp_path / "desktop-close.json"
    save_close_preference("quit", path)
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=path)
    controller.bind_window(window)

    result = controller.handle_window_closing()

    assert result is True
    assert not window.evaluated
    assert not window.destroyed


def test_vue_quit_choice_saves_and_destroys_window(tmp_path):
    path = tmp_path / "desktop-close.json"
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=path)
    controller.bind_window(window)

    result = controller.closeWithChoice("quit", True)

    assert result == {"ok": True, "action": "quit", "remember": True}
    assert load_close_preference(path) == "quit"
    assert window.destroyed


def test_force_quit_destroys_window(tmp_path):
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)

    result = controller.forceQuit()

    assert result == {"ok": True}
    assert window.destroyed


def test_vue_tray_choice_saves_and_hides_window(tmp_path):
    path = tmp_path / "desktop-close.json"
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=path)
    controller.bind_window(window)
    controller._ensure_tray_icon = lambda: True  # type: ignore[method-assign]

    result = controller.closeWithChoice("tray", True)

    assert result == {"ok": True, "action": "tray", "remember": True}
    assert load_close_preference(path) == "tray"
    assert window.hidden
    assert not window.destroyed


def test_tray_choice_falls_back_to_minimize_when_tray_unavailable(tmp_path):
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")
    controller.bind_window(window)
    controller._ensure_tray_icon = lambda: False  # type: ignore[method-assign]

    used_tray = controller.minimize_to_tray()

    assert used_tray is False
    assert window.minimized
    assert not window.hidden


def test_vue_tray_choice_does_not_persist_when_tray_unavailable(tmp_path):
    path = tmp_path / "desktop-close.json"
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=path)
    controller.bind_window(window)
    controller._ensure_tray_icon = lambda: False  # type: ignore[method-assign]

    result = controller.closeWithChoice("tray", True)

    assert result == {"ok": True, "action": "tray", "remember": True}
    assert load_close_preference(path) is None
    assert window.minimized


def test_remembered_tray_failure_clears_preference_and_reprompts(tmp_path):
    path = tmp_path / "desktop-close.json"
    save_close_preference("tray", path)
    window = FakeWindow()
    controller = DesktopCloseController(preference_path=path)
    controller.bind_window(window)
    controller._ensure_tray_icon = lambda: False  # type: ignore[method-assign]

    result = controller.handle_window_closing()

    assert result is False
    assert load_close_preference(path) is None
    assert len(window.evaluated) == 1
    assert "desktop-close-request" in window.evaluated[0]
    assert not window.minimized
    assert not window.destroyed


def test_invalid_close_choice_is_rejected(tmp_path):
    controller = DesktopCloseController(preference_path=tmp_path / "desktop-close.json")

    with pytest.raises(ValueError):
        controller.closeWithChoice("restart", False)


def test_tray_text_is_localized_from_vue_locale():
    assert get_tray_text("en")["show"] == "Open main window"
    assert get_tray_text("zh")["show"] == "打开主窗口"

    controller = DesktopCloseController()

    assert controller.setLocale("en-US") == {"ok": True, "locale": "en"}
    assert controller.locale_code == "en"
    assert controller.setLocale("zh-CN") == {"ok": True, "locale": "zh"}
    assert controller.locale_code == "zh"


def test_locale_sync_refreshes_existing_tray_text():
    controller = DesktopCloseController(title="YouTube Monitor")
    tray_icon = FakeTrayThing()
    show_item = FakeTrayThing()
    quit_item = FakeTrayThing()
    controller._tray_icon = tray_icon
    controller._tray_show_item = show_item
    controller._tray_quit_item = quit_item

    assert controller.setLocale("en-US") == {"ok": True, "locale": "en"}

    assert tray_icon.Text == "YouTube Monitor"
    assert tray_icon.BalloonTipTitle == "Minimized to tray"
    assert tray_icon.BalloonTipText.startswith("The app will keep running")
    assert show_item.Text == "Open main window"
    assert quit_item.Text == "Exit app"


def test_frontend_bridge_failure_falls_back_to_window_close():
    app_vue = (ROOT / "frontend-vue" / "src" / "App.vue").read_text(encoding="utf-8")
    bridge_ts = (ROOT / "frontend-vue" / "src" / "utils" / "desktopBridge.ts").read_text(
        encoding="utf-8",
    )
    handler = re.search(
        r"const handleDesktopCloseChoice = async \(choice: DesktopCloseChoice\) => \{(?P<body>.*?)\n\}",
        app_vue,
        re.S,
    )

    assert handler is not None
    assert "function isBridgeOk" in bridge_ts
    assert "result.ok === false" in bridge_ts
    assert "try {" in bridge_ts
    assert "catch (error)" in bridge_ts
    assert "return false" in bridge_ts
    assert "forceQuitDesktop" in app_vue
    assert "pywebviewready" in app_vue
    assert "getDesktopBridge" in app_vue
    assert "setDesktopCloseLocale" in app_vue
    assert "__YTDLP_PENDING_DESKTOP_CLOSE__" in app_vue
    assert "flushPendingDesktopCloseRequest" in app_vue
    assert "if (!handled)" in handler.group("body")
    assert "window.close()" in handler.group("body")
    assert "choice.action === 'quit'" in handler.group("body")
    assert "desktopCloseDialogVisible.value = true" in handler.group("body")


def test_frontend_custom_close_button_uses_desktop_dialog_before_wails_quit():
    screen_vue = (ROOT / "frontend-vue" / "src" / "components" / "Screen.vue").read_text(
        encoding="utf-8",
    )

    assert "requestDesktopClose" in screen_vue
    assert "const handled = await requestDesktopClose()" in screen_vue
    assert "if (!handled)" in screen_vue
    assert "Quit()" in screen_vue


def test_desktop_close_dialog_has_accessibility_and_mobile_guards():
    dialog_vue = (
        ROOT / "frontend-vue" / "src" / "components" / "DesktopCloseDialog.vue"
    ).read_text(encoding="utf-8")

    assert 'aria-modal="true"' in dialog_vue
    assert 'ref="dismissButton"' in dialog_vue
    assert "dismissButton.value?.focus()" in dialog_vue
    assert "max-height: min(640px, calc(100vh - 64px));" in dialog_vue
    assert "max-height: calc(100dvh - 32px);" in dialog_vue


def test_desktop_bridge_runtime_contract_with_mocked_pywebview():
    script = r"""
const fs = require('fs')
const assert = require('assert')
const ts = require('./frontend-vue/node_modules/typescript')
const vm = require('vm')

const source = fs.readFileSync('frontend-vue/src/utils/desktopBridge.ts', 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
  },
}).outputText

const sandbox = {
  exports: {},
  console: { warn: () => {} },
  window: {},
  CustomEvent: function CustomEvent(type) {
    this.type = type
  },
}
vm.createContext(sandbox)
vm.runInContext(compiled, sandbox, { filename: 'desktopBridge.js' })

const bridge = sandbox.exports

;(async () => {
  assert.strictEqual(bridge.getDesktopBridge(), undefined)
  assert.strictEqual(await bridge.closeWithDesktopChoice({ action: 'tray', remember: true }), false)

  const calls = []
  const events = []
  sandbox.window.dispatchEvent = (event) => {
    events.push(event.type)
    return true
  }
  sandbox.window.pywebview = {
    api: {
      closeWithChoice: async (action, remember) => {
        calls.push(['closeWithChoice', action, remember])
        return { ok: true }
      },
      requestClose: () => ({ ok: false }),
      setLocale: (locale) => {
        calls.push(['setLocale', locale])
        return { ok: true }
      },
      forceQuit: () => {
        calls.push(['forceQuit'])
        return { ok: true }
      },
    },
  }

  assert.strictEqual(await bridge.closeWithDesktopChoice({ action: 'tray', remember: true }), true)
  assert.deepStrictEqual(calls[0], ['closeWithChoice', 'tray', true])

  sandbox.window.__YTDLP_DESKTOP_CLOSE_READY__ = true
  assert.strictEqual(await bridge.requestDesktopClose(), true)
  assert.deepStrictEqual(events, ['desktop-close-request'])

  sandbox.window.__YTDLP_DESKTOP_CLOSE_READY__ = false
  assert.strictEqual(await bridge.requestDesktopClose(), false)
  assert.strictEqual(await bridge.setDesktopCloseLocale('en-US'), true)
  assert.strictEqual(await bridge.forceQuitDesktop(), true)

  sandbox.window.pywebview.api.closeWithChoice = () => ({ ok: false })
  assert.strictEqual(await bridge.closeWithDesktopChoice({ action: 'quit', remember: false }), false)

  sandbox.window.pywebview.api.closeWithChoice = () => {
    throw new Error('bridge unavailable')
  }
  assert.strictEqual(await bridge.closeWithDesktopChoice({ action: 'quit', remember: false }), false)
})().catch((error) => {
  console.error(error)
  process.exit(1)
})
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr

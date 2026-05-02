"""Desktop close handling for the pywebview monitor shell."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Literal

from utils.paths import get_data_dir

DesktopCloseAction = Literal["tray", "quit"]

_VALID_ACTIONS = {"tray", "quit"}
_PREFERENCE_FILENAME = "desktop-close-preferences.json"
_TRAY_TEXT = {
    "zh": {
        "balloon_title": "已最小化到托盘",
        "balloon_text": "应用将在后台继续运行。双击托盘图标可恢复窗口。",
        "show": "打开主窗口",
        "quit": "退出应用",
    },
    "en": {
        "balloon_title": "Minimized to tray",
        "balloon_text": "The app will keep running in the background. Double-click the tray icon to restore it.",
        "show": "Open main window",
        "quit": "Exit app",
    },
}
_SHOW_DIALOG_SCRIPT = """
(function () {
  if (!window.__YTDLP_DESKTOP_CLOSE_READY__) {
    return false;
  }
  if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.closeWithChoice) {
    return false;
  }
  window.dispatchEvent(new CustomEvent('desktop-close-request'));
  return true;
})()
""".strip()
_QUEUE_CLOSE_DIALOG_SCRIPT = """
(function () {
  window.__YTDLP_PENDING_DESKTOP_CLOSE__ = true;
  return true;
})()
""".strip()


def get_close_preference_path() -> Path:
    """Return the writable file used for the close-window remembered choice."""
    return Path(get_data_dir()) / _PREFERENCE_FILENAME


def _normalize_action(action: object) -> DesktopCloseAction:
    if action not in _VALID_ACTIONS:
        raise ValueError(f"Unsupported desktop close action: {action!r}")
    return action  # type: ignore[return-value]


def _normalize_locale(locale_code: object) -> str:
    if not isinstance(locale_code, str):
        return "zh"
    return "en" if locale_code.lower().startswith("en") else "zh"


def get_tray_text(locale_code: object) -> dict[str, str]:
    return _TRAY_TEXT[_normalize_locale(locale_code)]


def load_close_preference(path: str | os.PathLike[str] | None = None) -> DesktopCloseAction | None:
    """Load a remembered close action, returning None for missing or invalid data."""
    preference_path = Path(path) if path is not None else get_close_preference_path()
    try:
        raw = json.loads(preference_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    action = raw.get("action") if isinstance(raw, dict) else None
    if action in _VALID_ACTIONS:
        return action  # type: ignore[return-value]
    return None


def save_close_preference(
    action: DesktopCloseAction,
    path: str | os.PathLike[str] | None = None,
) -> None:
    """Persist the remembered close action."""
    action = _normalize_action(action)
    preference_path = Path(path) if path is not None else get_close_preference_path()
    preference_path.parent.mkdir(parents=True, exist_ok=True)
    preference_path.write_text(
        json.dumps({"action": action}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_close_preference(path: str | os.PathLike[str] | None = None) -> None:
    """Remove the remembered close action if one exists."""
    preference_path = Path(path) if path is not None else get_close_preference_path()
    try:
        preference_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


class DesktopCloseController:
    """Bridge object exposed to pywebview JavaScript and native close events."""

    def __init__(
        self,
        *,
        title: str = "YouTube Monitor",
        preference_path: str | os.PathLike[str] | None = None,
        locale_code: str = "zh",
        logger: logging.Logger | None = None,
    ) -> None:
        self.title = title
        self.preference_path = Path(preference_path) if preference_path is not None else None
        self.locale_code = _normalize_locale(locale_code)
        self._log = logger or logging.getLogger("monitor_ui.desktop_close")
        self._window = None
        self._allow_close = False
        self._pending_close_queued = False
        self._tray_icon = None
        self._tray_menu = None
        self._tray_show_item = None
        self._tray_quit_item = None

    def bind_window(self, window) -> None:
        self._window = window

    def requestClose(self):  # noqa: N802 - pywebview exposes JS API names as-is.
        """Show the Vue close dialog from JavaScript callers."""
        return {"ok": self.request_close_dialog()}

    def setLocale(self, locale_code: str):  # noqa: N802
        """Keep native tray copy aligned with the Vue locale."""
        self.locale_code = _normalize_locale(locale_code)
        self._refresh_tray_text()
        return {"ok": True, "locale": self.locale_code}

    def forceQuit(self):  # noqa: N802
        """Fallback quit entrypoint for a ready pywebview bridge."""
        self.quit_application()
        return {"ok": True}

    def closeWithChoice(self, action: str, remember: bool = False):  # noqa: N802
        """Apply the user's close-dialog choice from the Vue bridge."""
        action = _normalize_action(action)

        if action == "tray":
            used_tray = self.minimize_to_tray()
            if remember and used_tray:
                save_close_preference(action, self.preference_path)
            elif remember and not used_tray:
                clear_close_preference(self.preference_path)
        else:
            if remember:
                save_close_preference(action, self.preference_path)
            self.quit_application()

        return {"ok": True, "action": action, "remember": bool(remember)}

    def handle_window_closing(self):
        """Return False to cancel native close only when a handler took over."""
        if self._allow_close:
            return True

        action = load_close_preference(self.preference_path)
        if action == "quit":
            self._allow_close = True
            return True

        if action == "tray":
            if self.minimize_to_tray(allow_minimize_fallback=False):
                return False
            clear_close_preference(self.preference_path)
            self._log.warning("Remembered tray close preference was cleared because tray is unavailable")
            if self.request_close_dialog():
                return False
            self._allow_close = True
            return True

        if self.request_close_dialog():
            return False

        self._allow_close = True
        return True

    def request_close_dialog(self) -> bool:
        """Show the Vue dialog now, or queue it until the frontend bridge is ready."""
        if self.show_close_dialog():
            self._pending_close_queued = False
            return True
        if self._pending_close_queued:
            self._pending_close_queued = False
            return False
        if self.queue_close_dialog():
            self._pending_close_queued = True
            return True
        return False

    def show_close_dialog(self) -> bool:
        if self._window is None:
            return False
        try:
            return bool(self._window.evaluate_js(_SHOW_DIALOG_SCRIPT))
        except Exception as exc:
            self._log.warning("Failed to show desktop close dialog: %s", exc)
            return False

    def queue_close_dialog(self) -> bool:
        if self._window is None:
            return False
        try:
            return bool(self._window.evaluate_js(_QUEUE_CLOSE_DIALOG_SCRIPT))
        except Exception as exc:
            self._log.warning("Failed to queue desktop close dialog: %s", exc)
            return False

    def minimize_to_tray(self, *, allow_minimize_fallback: bool = True) -> bool:
        if self._window is None:
            return False

        if self._ensure_tray_icon():
            try:
                self._window.hide()
                return True
            except Exception as exc:
                self._log.warning("Failed to hide window to tray: %s", exc)

        if not allow_minimize_fallback:
            return False

        try:
            self._window.minimize()
            return False
        except Exception as exc:
            self._log.warning("Failed to minimize window: %s", exc)
            return False

    def restore_from_tray(self) -> None:
        if self._window is None:
            return
        try:
            self._window.show()
            self._window.restore()
        except Exception as exc:
            self._log.warning("Failed to restore window from tray: %s", exc)

    def quit_application(self) -> None:
        if self._window is None:
            return
        self._allow_close = True
        self.dispose()
        try:
            self._window.destroy()
        except Exception as exc:
            self._log.warning("Failed to close desktop window: %s", exc)

    def dispose(self) -> None:
        icon = self._tray_icon
        menu = self._tray_menu
        self._tray_icon = None
        self._tray_menu = None
        self._tray_show_item = None
        self._tray_quit_item = None
        if icon is not None:
            try:
                icon.Visible = False
                icon.Dispose()
            except Exception:
                pass
        if menu is not None:
            try:
                menu.Dispose()
            except Exception:
                pass

    def _ensure_tray_icon(self) -> bool:
        if self._tray_icon is not None:
            return True
        if os.name != "nt":
            return False

        try:
            import clr

            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            import System.Windows.Forms as WinForms
            from System.Drawing import Icon, SystemIcons
        except Exception as exc:
            self._log.warning("System tray is unavailable: %s", exc)
            return False

        try:
            icon = WinForms.NotifyIcon()
            try:
                icon.Icon = Icon.ExtractAssociatedIcon(sys.executable) or SystemIcons.Application
            except Exception:
                icon.Icon = SystemIcons.Application

            tray_text = get_tray_text(self.locale_code)
            icon.Text = self.title
            icon.BalloonTipTitle = tray_text["balloon_title"]
            icon.BalloonTipText = tray_text["balloon_text"]

            menu = WinForms.ContextMenuStrip()
            show_item = WinForms.ToolStripMenuItem(tray_text["show"])
            quit_item = WinForms.ToolStripMenuItem(tray_text["quit"])

            show_item.Click += lambda _sender, _args: self.restore_from_tray()
            quit_item.Click += lambda _sender, _args: self.quit_application()
            icon.DoubleClick += lambda _sender, _args: self.restore_from_tray()

            menu.Items.Add(show_item)
            menu.Items.Add(quit_item)
            icon.ContextMenuStrip = menu
            icon.Visible = True
            try:
                icon.ShowBalloonTip(2000)
            except Exception:
                pass

            self._tray_icon = icon
            self._tray_menu = menu
            self._tray_show_item = show_item
            self._tray_quit_item = quit_item
            self._refresh_tray_text()
            return True
        except Exception as exc:
            self._log.warning("Failed to create system tray icon: %s", exc)
            return False

    def _refresh_tray_text(self) -> None:
        if self._tray_icon is None:
            return

        tray_text = get_tray_text(self.locale_code)
        try:
            self._tray_icon.Text = self.title
            self._tray_icon.BalloonTipTitle = tray_text["balloon_title"]
            self._tray_icon.BalloonTipText = tray_text["balloon_text"]
            if self._tray_show_item is not None:
                self._tray_show_item.Text = tray_text["show"]
            if self._tray_quit_item is not None:
                self._tray_quit_item.Text = tray_text["quit"]
        except Exception as exc:
            self._log.warning("Failed to refresh system tray text: %s", exc)

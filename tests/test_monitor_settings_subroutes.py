# -*- coding: utf-8 -*-
"""Regression: 配置中心拆为独立 section + templates/pages/*.html 注入。"""

import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_settings_pages_are_separate_sections_and_templates():
    root = _repo_root()
    router = (root / "monitor_web" / "static" / "js" / "router.js").read_text(encoding="utf-8")
    html = (root / "monitor_web" / "index.html").read_text(encoding="utf-8")
    partials = (root / "monitor_web" / "js" / "load-partials.js").read_text(encoding="utf-8")

    assert "SETTINGS_SUB_PANEL_ID" not in router
    assert "pageDomId = 'page-' + name" in router

    for name in ("settings", "settings-notify", "settings-api", "settings-download", "settings-ai", "settings-dynamic"):
        assert f'id="page-{name}"' in html, f"missing section #page-{name}"

    for fname in (
        "settings-hub.html",
        "settings-notify.html",
        "settings-api.html",
        "settings-download.html",
        "settings-ai.html",
        "settings-dynamic.html",
    ):
        assert f"/templates/pages/{fname}" in partials, f"missing partial mapping for {fname}"
        p = root / "monitor_web" / "templates" / "pages" / fname
        assert p.is_file(), f"missing file {p}"

    assert 'id="tpl-page-settings"' in html
    assert 'id="cfgFeishu"' in (root / "monitor_web" / "templates" / "pages" / "settings-notify.html").read_text(encoding="utf-8")

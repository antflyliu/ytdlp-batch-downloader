# -*- coding: utf-8 -*-
"""Regression coverage for Vue overlays not shifting the app shell."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend-vue" / "src"
MAIN_CSS = SRC / "assets" / "css" / "main.css"
DYNAMIC_PROVIDERS = SRC / "views" / "DynamicProviders.vue"


OVERLAY_FILES = [
    SRC / "views" / "Accounts.vue",
    SRC / "views" / "ApiKeys.vue",
    SRC / "views" / "DynamicProviders.vue",
    SRC / "views" / "ProxyPools.vue",
    SRC / "components" / "ClipDetailModal.vue",
    SRC / "components" / "Footer.vue",
    SRC / "components" / "ImportJson.vue",
    SRC / "components" / "Password.vue",
    SRC / "components" / "Preview.vue",
]


def test_modal_css_does_not_lock_body_scroll():
    text = MAIN_CSS.read_text(encoding="utf-8")

    assert "body:has(.n-modal)" not in text
    assert "overflow: hidden !important;" not in text[
        text.index("Modal layout stability") : text.index("Modal card footer")
    ]
    assert "scrollbar-gutter: stable;" in text


def test_all_vue_overlays_opt_out_of_body_scroll_lock():
    missing: list[str] = []
    pattern = re.compile(r"<(?:NModal|n-modal|NDrawer)\b[^>]*>", re.MULTILINE)

    for path in OVERLAY_FILES:
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            tag = match.group(0)
            if ':block-scroll="false"' not in tag:
                rel = path.relative_to(ROOT).as_posix()
                missing.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1}")

    assert not missing, "Overlays missing :block-scroll=\"false\": " + ", ".join(missing)


def test_dynamic_provider_grid_form_items_render_labels():
    text = DYNAMIC_PROVIDERS.read_text(encoding="utf-8")

    assert "NGridItem as NFormItemGi" not in text
    assert "NFormItemGi" in text
    assert ':label="t(\'dynProviders.authUsername\')"' in text
    assert ':label="t(\'dynProviders.authPassword\')"' in text

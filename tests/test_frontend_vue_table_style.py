# -*- coding: utf-8 -*-
"""Regression coverage for Vue table fixed-column readability."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_CSS = ROOT / "frontend-vue" / "src" / "styles" / "layout.css"
RESOURCE_ACTION = ROOT / "frontend-vue" / "src" / "components" / "ResourceAction.vue"
DYNAMIC_PROVIDERS = ROOT / "frontend-vue" / "src" / "views" / "DynamicProviders.vue"


def test_table_header_stays_inside_table_surface():
    text = LAYOUT_CSS.read_text(encoding="utf-8")
    wrapper_rule_start = text.index(".app-sticky-table .n-data-table-wrapper")
    wrapper_rule = text[wrapper_rule_start : text.index("}", wrapper_rule_start)]
    base_header_rule_start = text.index(".app-sticky-table .n-data-table-base-table-header")
    base_header_rule = text[base_header_rule_start : text.index("}", base_header_rule_start)]
    header_rule_start = text.index(".app-sticky-table .n-data-table-thead .n-data-table-th")
    header_rule = text[header_rule_start : text.index("}", header_rule_start)]

    assert "overflow: hidden !important;" in wrapper_rule
    assert "position: relative !important;" in base_header_rule
    assert "top: auto !important;" in base_header_rule
    assert "top: var(--table-header-sticky-top)" not in base_header_rule
    assert "position: sticky" not in header_rule


def test_fixed_operation_column_has_opaque_surface_and_button_background():
    text = LAYOUT_CSS.read_text(encoding="utf-8")

    assert "--table-fixed-bg: #fffdf8;" in text
    assert ".app-sticky-table .n-data-table-td--fixed-right" in text
    assert "background-color: var(--table-fixed-bg) !important;" in text
    assert ".app-sticky-table .n-data-table-td--fixed-right .n-button" in text
    assert "background: var(--n-color) !important;" in text


def test_resource_actions_render_on_solid_action_rail():
    text = RESOURCE_ACTION.read_text(encoding="utf-8")

    assert 'class="resource-action"' in text
    assert "background: #fffdf8;" in text
    assert "min-width: max-content;" in text
    assert "flex-shrink: 0;" in text


def test_dynamic_provider_actions_use_compact_dropdown():
    text = DYNAMIC_PROVIDERS.read_text(encoding="utf-8")

    assert "NDropdown" in text
    assert "providerActionOptions" in text
    assert "handleProviderAction" in text
    assert "width: 128" in text
    assert "provider-row-actions" in text
    assert "provider-action-trigger" in text
    assert "flex-wrap:wrap" not in text[text.index("title: t('dynProviders.thActions')") :]

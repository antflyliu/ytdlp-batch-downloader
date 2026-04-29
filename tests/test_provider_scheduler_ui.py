from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"
DYN_PROV_JS = ROOT / "monitor_web" / "js" / "modules" / "dynamicProvider.js"


def _dyn_prov_js() -> str:
    return DYN_PROV_JS.read_text(encoding="utf-8")


def _tpl(name: str) -> str:
    return (ROOT / "monitor_web" / "templates" / "modals" / name).read_text(encoding="utf-8")


def test_dynamic_provider_workbench_has_detail_drawer_hooks():
    # HTML elements were extracted to templates/modals/dyn-provider-detail-drawer.html
    drawer_html = _tpl("dyn-provider-detail-drawer.html")
    for el_id in ["dynProviderDetailDrawer", "dynProviderDetailBody", "dynProviderDetailError",
                  "dynProviderDetailPreviewSummary", "dynProviderDetailFailures",
                  "dynProviderDetailActions", "dynProviderDetailFailuresToggle"]:
        assert f'id="{el_id}"' in drawer_html, f"Missing {el_id} in template"

    # JS functions are in modules/dynamicProvider.js
    js = _dyn_prov_js()
    for fn in ["function openDynamicProviderDetail(", "function closeDynamicProviderDetail(",
               "function refreshDynamicProviderDetail(", "function toggleProviderFailureList("]:
        assert fn in js, f"Missing {fn} in dynamicProvider.js"


def test_refresh_dynamic_provider_opens_detail_drawer_after_success():
    js = _dyn_prov_js()
    match = re.search(r"async function refreshDynamicProvider\(id\) \{([\s\S]*?)\n  \}", js)
    assert match, "refreshDynamicProvider() should exist"
    body = match.group(1)
    assert "openDynamicProviderDetail(id)" in body


def test_provider_rows_show_last_refresh_time_hook():
    # "上次刷新" label is rendered by the JS module, not in static HTML
    js = _dyn_prov_js()
    assert '上次刷新' in js or 'last_refresh' in js.lower()


def test_dynamic_provider_table_rows_use_accounts_style_actions_div():
    """与账户列表一致：操作列用 .actions + .btn-sm，避免窄列内文字竖排。"""
    js = _dyn_prov_js()
    assert 'class="actions"' in js
    assert "dyn-actions" not in js


def test_dynamic_providers_page_scheduler_toolbar_uses_bem_buttons():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "dyn-scheduler-card__toolbar" in html
    assert 'class="btn btn--sm btn--success"' in html
    assert "btnDynProviderSchedulerToggle" in html

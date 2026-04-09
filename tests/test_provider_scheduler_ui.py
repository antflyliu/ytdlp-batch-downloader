from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"


def test_dynamic_provider_workbench_has_detail_drawer_hooks():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="dynProviderDetailDrawer"' in html
    assert 'id="dynProviderDetailBody"' in html
    assert 'id="dynProviderDetailError"' in html
    assert 'id="dynProviderDetailPreviewSummary"' in html
    assert 'id="dynProviderDetailFailures"' in html
    assert 'id="dynProviderDetailActions"' in html
    assert 'id="dynProviderDetailFailuresToggle"' in html
    assert 'function openDynamicProviderDetail(' in html
    assert 'function closeDynamicProviderDetail(' in html
    assert 'function refreshDynamicProviderDetail(' in html
    assert 'function toggleProviderFailureList(' in html


def test_refresh_dynamic_provider_opens_detail_drawer_after_success():
    html = INDEX_HTML.read_text(encoding="utf-8")
    match = re.search(r"async function refreshDynamicProvider\(id\) \{([\s\S]*?)\n  \}", html)
    assert match, "refreshDynamicProvider() should exist"
    body = match.group(1)
    assert "openDynamicProviderDetail(id)" in body


def test_provider_rows_show_last_refresh_time_hook():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert '上次刷新:' in html or 'last refresh' in html.lower()

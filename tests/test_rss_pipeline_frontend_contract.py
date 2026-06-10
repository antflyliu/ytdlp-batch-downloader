from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RSS_PIPELINE_VIEW = ROOT / "frontend-vue" / "src" / "views" / "RssPipeline.vue"


def test_rss_pipeline_imports_naive_components_used_in_template():
    text = RSS_PIPELINE_VIEW.read_text(encoding="utf-8")
    import_end = text.index("from 'naive-ui'")
    import_start = text.rindex("import {", 0, import_end)
    import_block = text[import_start:import_end]

    for name in (
        "NAlert",
        "NButton",
        "NCard",
        "NCheckbox",
        "NEmpty",
        "NForm",
        "NFormItem",
        "NInput",
        "NInputNumber",
        "NPopconfirm",
        "NSelect",
        "NTag",
    ):
        assert name in import_block

    for name in ("NButton", "NInput"):
        assert f"<{name}" in text


def test_rss_pipeline_matches_native_collect_workbench_layout():
    text = RSS_PIPELINE_VIEW.read_text(encoding="utf-8")

    for snippet in (
        'class="rss-workbench"',
        'class="rss-sidebar-stack"',
        'class="rss-card rss-feeds-card"',
        'class="rss-card rss-catalog-card"',
        'class="rss-card rss-items-card"',
        'class="rss-card rss-opml-card"',
        '<template #header-extra>',
    ):
        assert snippet in text

    for style in (
        "grid-template-columns: minmax(340px, 0.72fr) minmax(0, 1.28fr);",
        "min-height: clamp(620px, 74vh, 820px);",
        "max-height: clamp(260px, 35vh, 420px);",
        "max-height: clamp(260px, 32vh, 390px);",
        "overflow-y: auto;",
        "border-radius: 20px;",
        "rgba(201, 100, 66, 0.07)",
        "transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;",
        "@media (max-width: 960px)",
    ):
        assert style in text

    for snippet in (
        "catalogEntries",
        "syncRssCatalog",
        "importRssCatalogEntries",
        "rsshubBase",
        "rss-catalog-entry--imported",
    ):
        assert snippet in text

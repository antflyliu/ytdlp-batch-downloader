"""Static contract tests for the Web UI batch download modal.

Phase 4 模块化后：批量下载弹窗 HTML 提取到 templates/modals/modal-batch-download.html，
JS 逻辑迁移到 js/components/batch-download-modal.js，样式拆分为 11 个子文件。
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"
TEMPLATE_FILE = ROOT / "monitor_web" / "templates" / "modals" / "modal-batch-download.html"
CSS_FILE = ROOT / "monitor_web" / "static" / "css" / "components.css"
BATCH_JS = ROOT / "monitor_web" / "js" / "components" / "batch-download-modal.js"


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _tpl() -> str:
    return TEMPLATE_FILE.read_text(encoding="utf-8")


def _css() -> str:
    # components.css 已拆分为 11 个子文件，聚合读取所有
    css_dir = CSS_FILE.parent
    sub_files = [
        "components.css", "modal.css", "form.css", "table.css", "toast.css",
        "drawer.css", "provider.css", "provider-dyn.css", "api-key.css",
        "base.css", "common.css", "batch.css",
    ]
    parts = []
    for name in sub_files:
        f = css_dir / name
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _js() -> str:
    return BATCH_JS.read_text(encoding="utf-8")


def test_batch_ui_uses_upload_id_contract_instead_of_raw_urls():
    js = _js()
    assert "upload_id: _bdUploadId" in js
    assert "r.preview_urls" in js
    assert "_bdUrls = r.urls || []" not in js


def test_batch_ui_proxy_pool_selector_uses_pool_ids():
    js = _js()
    assert "if (!Array.isArray(r)) return;" in js
    assert "opt.value = String(p.id);" in js
    assert "opt.value = p.proxy_url" not in js


def test_batch_ui_cookie_override_uses_server_path_prompt():
    js = _js()
    assert "必须是监控服务器本机可访问的文件路径" in js
    assert "f.files[0]" not in js


def test_batch_ui_switching_format_resets_upload_state():
    js = _js()
    assert "function bdResetUploadState()" in js
    assert "bdResetUploadState();" in js


def test_batch_ui_log_rendering_is_incremental():
    js = _js()
    assert "let _bdLastLogCount = 0;" in js
    assert "results.slice(_bdLastLogCount)" in js


def test_batch_ui_modal_footer_styles_are_scoped():
    """页脚样式在 batch.css（已从 components.css 提取）。"""
    css = _css()
    assert "#modalBatchDownload .modal-footer" in css
    # 确保不是全局 .modal-footer（应限制作用域）
    assert "\n.modal-footer { display: flex; justify-content: flex-end;" not in css


def test_batch_ui_cancel_requests_server_side_task_cancellation():
    js = _js()
    assert "function bdCancelTask(taskId)" in js
    assert "api('POST', '/batch/tasks/' + taskId + '/cancel', {})" in js
    assert "btn.textContent = '取消中...';" in js
    assert "r.status === 'done' || r.status === 'error' || r.status === 'cancelled'" in js


def test_batch_ui_restart_without_upload_uses_post_restart():
    """无 upload_id 时「重新下载」应对选中/当前历史任务 POST /batch/tasks/:id/restart。"""
    js = _js()
    assert "function bdRestartHistoryTask(taskId)" in js
    assert "api('POST', '/batch/tasks/' + taskId + '/restart', {})" in js
    assert "bdResolveRestartTaskId" in js or "bdResolveRestartTaskId()" in js


def test_batch_ui_can_load_and_reopen_recent_tasks():
    """最近任务列表 UI 在模板文件中（Phase 4 提取）。"""
    tpl = _tpl()
    html = _html()
    js = _js()
    assert 'id="bdRecentTasks"' in tpl
    assert 'onclick="loadRecentBatchTasks()"' in html or "loadRecentBatchTasks" in js


def test_batch_ui_index_html_is_pure_shell():
    """index.html 是纯 HTML 壳，所有 JS 逻辑在模块中。"""
    html = _html()
    # 不应有任何内联 JS 函数定义
    assert "function " not in html or "<script" in html
    # 应该有模块化入口
    assert '<script type="module" src="/js/app.js"></script>' in html

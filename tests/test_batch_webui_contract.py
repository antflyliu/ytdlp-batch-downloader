"""Static contract tests for the Web UI batch download modal."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "monitor_web" / "index.html"


def _html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_batch_ui_uses_upload_id_contract_instead_of_raw_urls():
    html = _html()
    assert "upload_id: _bdUploadId" in html
    assert "r.preview_urls" in html
    assert "_bdUrls = r.urls || []" not in html


def test_batch_ui_proxy_pool_selector_uses_pool_ids():
    html = _html()
    assert "if (!Array.isArray(r)) return;" in html
    assert "opt.value = String(p.id);" in html
    assert "opt.value = p.proxy_url" not in html
    assert "proxy_pool_id: document.getElementById('bdProxy').value || null" in html


def test_batch_ui_cookie_override_uses_server_path_prompt():
    html = _html()
    assert "必须是监控服务器本机可访问的文件路径" in html
    assert "f.files[0]" not in html


def test_batch_ui_switching_format_resets_upload_state():
    html = _html()
    assert "function bdResetUploadState()" in html
    assert "bdResetUploadState();" in html


def test_batch_ui_log_rendering_is_incremental():
    html = _html()
    assert "let _bdLastLogCount = 0;" in html
    assert "results.slice(_bdLastLogCount)" in html


def test_batch_ui_modal_footer_styles_are_scoped():
    html = _html()
    assert "#modalBatchDownload .modal-footer" in html
    assert "\n.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px; border-top: 1px solid var(--border); }" not in html


def test_batch_ui_cancel_requests_server_side_task_cancellation():
    html = _html()
    assert "function bdCancelTask(taskId)" in html
    assert "api('POST', '/batch/tasks/' + taskId + '/cancel', {})" in html
    assert "btn.textContent = '取消中...';" in html
    assert "r.status === 'done' || r.status === 'error' || r.status === 'cancelled'" in html


def test_batch_ui_can_load_and_reopen_recent_tasks():
    html = _html()
    assert 'id="bdRecentTasks"' in html
    assert 'id="bdRecentList"' in html
    assert 'id="bdRecentSummary"' in html
    assert 'data-filter="all"' in html
    assert 'data-filter="active"' in html
    assert 'data-filter="finished"' in html
    assert 'data-filter="cancelled"' in html
    assert "let _bdRecentFilter = 'all';" in html
    assert "function bdSetRecentFilter(filter, btn)" in html
    assert "function bdFilterRecentTasks(tasks)" in html
    assert "function bdUpdateRecentSummary(tasks)" in html
    assert "function bdRenderRecentTaskCards(tasks, activeTaskId)" in html
    assert "tasks.slice(0, 6).forEach(task => {" in html
    assert "reopenBtn.textContent = '重开';" in html
    assert "cancelBtn.textContent = task.status === 'cancelling' ? '取消中...' : '取消';" in html
    assert "bdCancelTask(task.task_id);" in html
    assert "function loadRecentBatchTasks(selectedTaskId)" in html
    assert "api('GET', '/batch/tasks')" in html
    assert "function bdOpenSelectedTask()" in html
    assert "function bdAttachTask(taskId)" in html
    assert "bdApplyTaskSnapshot(task, true);" in html

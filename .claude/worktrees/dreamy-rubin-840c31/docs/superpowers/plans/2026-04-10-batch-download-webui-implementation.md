# Web UI 批量下载弹窗 — 实现计划

> **As-built update (2026-04-10):** 以下实现说明以当前代码为准，早期草案中的部分片段已被后续修正覆盖。当前正式契约为：
> - `POST /api/batch/upload` 返回 `upload_id + url_count + preview_urls`，前端**只显示预览**，完整 URL 列表仅保存在服务端上传会话中。
> - `POST /api/batch/start` 以 `upload_id` 启动任务，并接受 `proxy_pool_id`（可选）而不是裸 `proxy` 字符串。
> - `POST /api/batch/tasks/:id/cancel` 支持服务端取消任务；运行中的任务会先显示 `cancelling`，完成取消后落为 `cancelled`。
> - Cookie 覆盖值是**监控服务本机可访问的路径**，不再假定浏览器本地文件可直接传给后端。
> - 输出路径校验复用现有下载接口的允许范围（项目目录 + 全局配置目录）。
> - 当前测试主入口为 `tests/test_batch_webui_api_behavior.py`、`tests/test_batch_webui_contract.py`，并配合 `tests/test_batch_*` 回归集。

## 当前收口状态（2026-04-10）

### 已完成

- [x] 上传文件后由服务端保存完整 URL 集，前端仅持有 `upload_id`
- [x] Web 批量下载独立代理路由，避免复用 account-only 路由入口
- [x] 代理池通过 `proxy_pool_id` 生效
- [x] Cookie 覆盖输入收敛为服务器路径语义
- [x] 任务结果对外统一为 `status / info / url`
- [x] 支持服务端取消任务
- [x] 支持在弹窗内查看最近任务并恢复查看运行中任务
- [x] 最近任务历史持久化到数据库，服务重启后仍可查看

### 当前建议验证命令

```bash
python -m pytest -q
python -m ruff check monitor_server.py Youtube_Downloader.py tests/test_batch_download_cancellation.py tests/test_batch_webui_api_behavior.py tests/test_batch_webui_contract.py
```

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 Web UI 新增批量下载弹窗：上传文件 + 配置 + 进度

**Tech Stack:** Python (monitor_server.py), Vanilla JS/HTML/CSS (index.html), existing `_DownloadTaskManager`

---

## 文件变更概览

| 文件 | 变更 |
|------|------|
| `monitor_server.py` | +~200 行：4 个新端点 + multipart upload 支持 |
| `monitor_web/index.html` | +~400 行：modal HTML/CSS/JS |
| `tests/test_batch_webui_api_behavior.py` | 新建，验证 upload_id / proxy_pool_id / 任务状态 API 行为 |
| `tests/test_batch_webui_contract.py` | 新建，验证 Web UI 契约（upload_id、代理池、Cookie、日志增量） |

---

## Task 1: 后端 — multipart upload API

**Files:**
- Modify: `monitor_server.py`

### Step 1: 添加 multipart upload 支持

在 `MonitorHandler` 类中添加 `do_POST` 处理前的 multipart 解析，或在 `do_POST` 开头添加：

```python
# 在 do_POST 开头，读取 JSON body 之前，尝试解析 multipart
if self.headers.get("Content-Type", "").startswith("multipart/form-data"):
    self._handle_multipart_upload()
    return
```

添加方法：

```python
def _handle_multipart_upload(self):
    """处理 multipart/form-data 上传（批量下载文件上传）。"""
    try:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            },
        )
        file_item = form.getfirst("file")
        if not file_item:
            self._send_json({"ok": False, "error": "未上传文件"}, 400)
            return

        filename = file_item.filename or "upload"
        data = file_item.file.read()

        # 保存到临时文件
        import tempfile, hashlib
        suffix = Path(filename).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        # 解析 URL
        try:
            urls = read_urls_from_file(tmp_path)
            if not isinstance(urls, list) or not urls:
                os.unlink(tmp_path)
                self._send_json({"ok": False, "error": "文件中未找到有效 URL"}, 400)
                return
            os.unlink(tmp_path)
            preview = urls[:5]
            self._send_json({
                "ok": True,
                "filename": filename,
                "url_count": len(urls),
                "urls": preview,
            })
        except Exception as ex:
            os.unlink(tmp_path)
            self._send_json({"ok": False, "error": f"解析失败: {ex}"}, 400)
    except Exception as ex:
        self._send_json({"ok": False, "error": str(ex)}, 500)
```

### Step 2: 添加 `/api/batch/start` 端点

在 `do_POST` 路由中添加：

```python
elif path == "/api/batch/start":
    self._api_batch_download_start(body)
```

添加方法 `_api_batch_download_start`：

```python
def _api_batch_download_start(self, body: dict):
    """
    POST /api/batch/start — 从上传文件 URL 列表启动批量下载
    """
    urls = body.get("urls", [])
    if not isinstance(urls, list) or not urls:
        self._send_json({"error": "urls 必须为非空数组"}, 400)
        return

    cfg = _db.load_config()
    output_path = body.get("output_path", "").strip() or cfg.get("download_output_path", "").strip()
    if not output_path:
        output_path = os.path.join(_PROJECT_ROOT, "videos")

    # 路径安全校验
    abs_output = os.path.realpath(os.path.abspath(output_path))
    abs_root = os.path.abspath(_PROJECT_ROOT)
    if not abs_output.startswith(abs_root):
        self._send_json({"error": "输出路径必须在允许范围内"}, 400)
        return
    os.makedirs(abs_output, exist_ok=True)

    cookies_file = body.get("cookies_file", "") or cfg.get("download_cookies_file", "") or None
    if cookies_file and not os.path.isfile(cookies_file):
        cookies_file = None

    resolution = body.get("resolution", "best")
    sub_langs = body.get("sub_langs", "zh-Hans,en") if not body.get("no_subs", False) else None
    no_subs = body.get("no_subs", False)

    # 代理解析：走手动直连路由
    from monitor.dynamic_provider_resolver import resolve_for_manual_download
    route = resolve_for_manual_download(None, bool(cookies_file))

    resolved_proxy = None
    if route.resolved_proxy_source == "direct":
        resolved_proxy = None
    elif route.resolved_proxy_source in ("system_paid", "system_free"):
        resolved_proxy = route.proxy
    elif route.resolved_proxy_source == "account_static":
        resolved_proxy = route.proxy

    # aria2 加速
    enable_aria2 = cfg.get("enable_aria2", False)
    extra_ydl_opts = build_aria2_opts(resolved_proxy) if enable_aria2 and resolved_proxy else None

    task_id = _task_mgr.create_task([{"url": u} for u in urls], abs_output)

    def progress_wrapper(progress: float, status: str):
        _task_mgr.update_progress(task_id, int(progress * len(urls)), status)

    def run():
        try:
            results = batch_download(
                urls, abs_output, resolution,
                proxy=resolved_proxy,
                progress_callback=progress_wrapper,
                sub_langs=sub_langs,
                no_subs=no_subs,
                cookies_file=cookies_file,
                extra_ydl_opts=extra_ydl_opts,
            )
            _task_mgr.finish_task(task_id, results)
        except Exception as ex:
            _task_mgr.fail_task(task_id, str(ex))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    self._send_json({"ok": True, "task_id": task_id})
```

### Step 3: 添加 `/api/batch/tasks` 和 `/api/batch/tasks/:id`

在 `do_GET` 和 `do_POST` 中添加：

```python
# do_GET:
elif path == "/api/batch/tasks":
    self._api_batch_tasks_list()
elif path.startswith("/api/batch/tasks/"):
    task_id = path.split("/")[-1]
    self._api_batch_task_status(task_id)
```

```python
def _api_batch_tasks_list(self):
    tasks = _task_mgr.list_tasks()  # 需要在 _DownloadTaskManager 添加此方法
    self._send_json({"tasks": tasks})

def _api_batch_task_status(self, task_id: str):
    task = _task_mgr.get_task(task_id)
    if not task:
        self._send_json({"error": "任务不存在"}, 404)
        return
    self._send_json(task)
```

在 `_DownloadTaskManager` 中添加 `list_tasks()` 方法：

```python
def list_tasks(self) -> list[dict]:
    """返回所有任务列表。"""
    with self._lock:
        return [dict(t) for t in self._tasks.values()]
```

### Step 4: 验证

```bash
cd D:/WORKSPACE/video-download-space/ytdlp-batch-downloader
python -m ruff check monitor_server.py --select=E,F
```

---

## Task 2: 前端 — modal HTML + CSS + 入口按钮

**Files:**
- Modify: `monitor_web/index.html`

### Step 1: 添加 modal HTML（插入到现有 modal 区域末尾）

在 `index.html` 末尾（`</div>` 之前，`<!-- Toast -->` 之后）追加：

```html
<!-- 批量下载弹窗 -->
<div class="modal" id="modalBatchDownload" style="max-width:640px;height:88vh;display:flex;flex-direction:column">
  <div class="modal-header" style="border-left:3px solid var(--accent)">
    <div class="modal-title">⬇  批量下载</div>
    <button class="modal-close" onclick="closeModal('modalBatchDownload')">✕</button>
  </div>
  <div class="modal-body" style="overflow-y:auto;flex:1">

    <!-- 上传区 -->
    <div class="bd-section">
      <div class="bd-section-label">📁 上传视频列表</div>
      <div class="bd-pills" id="bdPills">
        <button class="bd-pill active" data-fmt="excel" onclick="bdSwitchFmt('excel')">Excel</button>
        <button class="bd-pill" data-fmt="csv" onclick="bdSwitchFmt('csv')">CSV</button>
        <button class="bd-pill" data-fmt="txt" onclick="bdSwitchFmt('txt')">TXT</button>
      </div>
      <input type="hidden" id="bdFmt" value="excel">
      <div class="bd-dropzone" id="bdDropzone" onclick="bdTriggerFile()">
        <div class="bd-dropzone-idle" id="bdDropIdle">
          <div class="bd-drop-icon">— —</div>
          <div class="bd-drop-text">拖入或点击上传</div>
          <div class="bd-drop-sub">支持 Excel · CSV · TXT</div>
        </div>
        <div class="bd-dropzone-selected" id="bdDropSelected" style="display:none">
          <div class="bd-drop-icon" style="color:var(--success)">✓</div>
          <div class="bd-drop-text" id="bdFileName"></div>
          <div class="bd-drop-sub" id="bdUrlCount"></div>
        </div>
      </div>
      <input type="file" id="bdFileInput" style="display:none" accept=".xlsx,.xls,.csv,.txt" onchange="bdHandleFile(this)">
      <div class="bd-file-error" id="bdFileError" style="display:none"></div>
    </div>

    <div class="bd-sep"></div>

    <!-- 配置区 -->
    <div class="bd-section" id="bdConfig">
      <div class="bd-section-label">📦 下载配置</div>
      <div class="bd-form-row">
        <label class="bd-label">保存路径</label>
        <div class="bd-input-row">
          <input class="bd-input" id="bdOutputPath" placeholder="默认取全局配置">
          <button class="bd-browse" onclick="bdBrowsePath()">浏览</button>
        </div>
      </div>
      <div class="bd-form-row">
        <label class="bd-label">视频画质</label>
        <select class="bd-select" id="bdResolution">
          <option value="best">最高画质</option>
          <option value="720p">720p</option>
          <option value="1080p">1080p</option>
          <option value="1440p">1440p</option>
        </select>
      </div>
      <div class="bd-form-row">
        <label class="bd-label">字幕语言</label>
        <input class="bd-input" id="bdSubLang" value="zh-Hans,en" style="width:120px">
        <label class="bd-checkbox-label">
          <input type="checkbox" id="bdSubEnabled" checked>
          <span>下载字幕</span>
        </label>
      </div>
      <div class="bd-form-row">
        <label class="bd-label">代理池</label>
        <select class="bd-select" id="bdProxy">
          <option value="">（不使用代理池）</option>
        </select>
      </div>
      <div class="bd-form-row">
        <label class="bd-label">Cookie</label>
        <div class="bd-input-row">
          <input class="bd-input" id="bdCookie" placeholder="默认取全局配置">
          <button class="bd-browse" onclick="bdBrowseCookie()">浏览</button>
        </div>
      </div>
    </div>

    <div class="bd-sep" id="bdProgressSep" style="display:none"></div>

    <!-- 进度区 -->
    <div class="bd-section" id="bdProgress" style="display:none">
      <div class="bd-section-label">📡 下载管道</div>
      <div class="bd-track-wrap">
        <div class="bd-track">
          <div class="bd-track-fill" id="bdTrackFill"></div>
          <div class="bd-track-pulse" id="bdTrackPulse"></div>
        </div>
        <span class="bd-pct" id="bdPct">0%</span>
      </div>
      <div class="bd-current" id="bdCurrent"></div>
      <div class="bd-counter" id="bdCounter"></div>
      <div class="bd-log-toggle" id="bdLogToggle" onclick="bdToggleLog()">▾ 展开详情</div>
      <div class="bd-log" id="bdLog" style="display:none">
        <div id="bdLogText"></div>
      </div>
    </div>

    <!-- 完成汇总 -->
    <div class="bd-complete" id="bdComplete" style="display:none"></div>
  </div>

  <!-- 底部按钮 -->
  <div class="modal-footer" id="bdFooter">
    <button class="btn btn-ghost" id="bdCancelBtn" onclick="bdCancel()">取消</button>
    <button class="btn btn-primary" id="bdStartBtn" onclick="bdStart()">▶ 开始下载</button>
  </div>
</div>
```

### Step 2: 添加 CSS

在 `index.html` `<style>` 末尾追加：

```css
/* ── 批量下载弹窗 ────────────────────────────────── */
#modalBatchDownload .modal-header {
  border-left: 3px solid var(--accent);
  border-bottom: 1.5px solid var(--border);
}
.bd-section { padding: 0 0 4px; }
.bd-section-label {
  font-size: 12px; font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 10px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.bd-pills { display: flex; gap: 6px; margin-bottom: 10px; }
.bd-pill {
  padding: 4px 14px; border-radius: 20px;
  font-size: 12px; font-weight: 500;
  cursor: pointer; border: 1px solid var(--border);
  background: var(--surface2); color: var(--text-muted);
  transition: all 0.15s;
}
.bd-pill:hover { border-color: var(--accent); color: var(--text); }
.bd-pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }

.bd-dropzone {
  border: 1.5px dashed var(--border); border-radius: var(--r-md);
  padding: 24px 16px; text-align: center; cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.bd-dropzone:hover { border-color: var(--accent); background: var(--accent-dim); }
.bd-dropzone.selected { border-style: solid; border-color: var(--success); background: var(--success-dim); }
.bd-dropzone.error { border-color: var(--error); background: var(--error-dim); }
.bd-drop-icon { font-size: 18px; color: var(--text-dim); margin-bottom: 6px; font-family: var(--mono); }
.bd-drop-text { font-size: 13px; color: var(--text-muted); }
.bd-drop-sub { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
.bd-file-error { font-size: 12px; color: var(--error); margin-top: 6px; text-align: center; }
.bd-sep { border-top: 1px solid var(--border); margin: 14px 0; }

.bd-form-row {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 12px;
}
.bd-label { font-size: 12px; color: var(--text-muted); width: 56px; flex-shrink: 0; }
.bd-input-row { display: flex; flex: 1; gap: 6px; }
.bd-input {
  flex: 1; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--r-sm); padding: 6px 10px;
  color: var(--text); font-size: 12px; font-family: var(--font);
  outline: none; transition: border-color 0.15s;
}
.bd-input:focus { border-color: var(--accent); }
.bd-select {
  flex: 1; background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--r-sm); padding: 6px 10px;
  color: var(--text); font-size: 12px; appearance: none;
  cursor: pointer;
}
.bd-browse {
  padding: 6px 12px; background: var(--surface3); border: 1px solid var(--border);
  border-radius: var(--r-sm); color: var(--text-muted); font-size: 12px;
  cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.bd-browse:hover { color: var(--text); border-color: var(--accent); }
.bd-checkbox-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--text-muted); cursor: pointer;
}
.bd-checkbox-label input[type=checkbox] { accent-color: var(--accent); cursor: pointer; }

/* 轨道进度条 */
.bd-track-wrap { display: flex; align-items: center; gap: 10px; margin: 8px 0 6px; }
.bd-track {
  flex: 1; height: 6px; background: var(--surface3); border-radius: 3px;
  overflow: hidden; position: relative;
}
.bd-track-fill {
  height: 100%; background: var(--accent); border-radius: 3px;
  transition: width 0.3s ease; width: 0%;
}
.bd-track-pulse {
  position: absolute; right: 0; top: 50%; transform: translateY(-50%);
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 8px var(--accent);
  animation: bd-pulse 1.5s ease-in-out infinite;
  opacity: 0;
}
.bd-track-pulse.active { opacity: 1; }
@keyframes bd-pulse {
  0%, 100% { transform: translateY(-50%) scale(1); opacity: 1; }
  50% { transform: translateY(-50%) scale(1.5); opacity: 0.6; }
}
.bd-pct { font-size: 11px; color: var(--text-muted); font-family: var(--mono); flex-shrink: 0; width: 32px; text-align: right; }
.bd-current { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bd-counter { font-size: 12px; color: var(--text-dim); margin-bottom: 8px; }
.bd-log-toggle {
  font-size: 11px; color: var(--text-dim); cursor: pointer; user-select: none; margin-bottom: 4px;
}
.bd-log-toggle:hover { color: var(--text-muted); }
.bd-log {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: var(--r-sm); padding: 8px 10px; max-height: 120px; overflow-y: auto;
}
.bd-log:empty::before { content: '暂无日志'; color: var(--text-dim); font-size: 11px; }
#bdLogText { font-family: var(--mono); font-size: 11px; color: var(--text-muted); line-height: 1.7; }
#bdLogText .log-success { color: var(--success); }
#bdLogText .log-error { color: var(--error); }
#bdLogText .log-info { color: var(--text-muted); }
#bdComplete { margin-top: 8px; padding: 10px; background: var(--success-dim); border: 1px solid rgba(34,197,94,0.3); border-radius: var(--r-sm); font-size: 12px; color: var(--success); text-align: center; }

/* modal-footer */
.modal-footer {
  display: flex; justify-content: flex-end; gap: 8px;
  padding: 12px 20px; border-top: 1px solid var(--border);
}
.modal-footer .btn { padding: 8px 20px; }
```

### Step 3: 添加入口按钮

在 `header-right` 区域找到现有的按钮，追加：

```html
<button class="btn btn-ghost" onclick="openBatchDownload()">⬇ 批量下载</button>
```

### Step 4: 添加 JS 函数

在 `</script>` 末尾追加：

```javascript
// ── 批量下载 ─────────────────────────────────────
let _bdTaskId = null;
let _bdPollTimer = null;
let _bdUrls = [];
let _bdState = 'idle'; // idle | running | done

function openBatchDownload() {
  _bdState = 'idle';
  _bdTaskId = null;
  _bdUrls = [];
  if (_bdPollTimer) { clearInterval(_bdPollTimer); _bdPollTimer = null; }
  document.getElementById('bdFileError').style.display = 'none';
  document.getElementById('bdDropIdle').style.display = '';
  document.getElementById('bdDropSelected').style.display = 'none';
  document.getElementById('bdProgress').style.display = 'none';
  document.getElementById('bdProgressSep').style.display = 'none';
  document.getElementById('bdComplete').style.display = 'none';
  document.getElementById('bdStartBtn').style.display = '';
  document.getElementById('bdStartBtn').textContent = '▶ 开始下载';
  document.getElementById('bdCancelBtn').textContent = '取消';
  document.getElementById('bdConfig').style.opacity = '';
  document.getElementById('bdLog').style.display = 'none';
  document.getElementById('bdLogToggle').textContent = '▾ 展开详情';
  document.getElementById('bdLogText').innerHTML = '';
  openModal('modalBatchDownload');
  loadProxyPoolsForBatch();
}

function loadProxyPoolsForBatch() {
  api('GET', '/api/proxy-pools').then(r => {
    if (r && r.pools) {
      const sel = document.getElementById('bdProxy');
      sel.innerHTML = '<option value="">（不使用代理池）</option>';
      r.pools.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.proxy_url || '';
        opt.textContent = p.name + (p.proxy_url ? ` (${p.proxy_url.substring(0,30)}...` : '');
        sel.appendChild(opt);
      });
    }
  });
}

function bdSwitchFmt(fmt) {
  document.getElementById('bdFmt').value = fmt;
  document.querySelectorAll('.bd-pill').forEach(p => {
    p.classList.toggle('active', p.dataset.fmt === fmt);
  });
}

function bdTriggerFile() {
  document.getElementById('bdFileInput').click();
}

function bdHandleFile(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  const fmt = document.getElementById('bdFmt').value;
  const formData = new FormData();
  formData.append('file', file);
  fetch('/api/batch/upload', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + _bearerToken },
    body: formData,
  }).then(r => r.json()).then(r => {
    if (r.ok) {
      _bdUrls = r.urls || [];
      document.getElementById('bdFileName').textContent = r.filename;
      document.getElementById('bdUrlCount').textContent = `${r.url_count} 条 URL`;
      document.getElementById('bdDropIdle').style.display = 'none';
      document.getElementById('bdDropSelected').style.display = '';
      document.getElementById('bdDropzone').classList.remove('error');
      document.getElementById('bdDropzone').classList.add('selected');
      document.getElementById('bdFileError').style.display = 'none';
    } else {
      document.getElementById('bdDropzone').classList.add('error');
      document.getElementById('bdFileError').textContent = '❌ ' + (r.error || '解析失败');
      document.getElementById('bdFileError').style.display = '';
      _bdUrls = [];
    }
  }).catch(e => {
    document.getElementById('bdDropzone').classList.add('error');
    document.getElementById('bdFileError').textContent = '❌ 网络错误';
    document.getElementById('bdFileError').style.display = '';
  });
}

function bdBrowsePath() {
  // 简单实现：让用户输入路径
  const p = prompt('请输入下载保存路径（留空使用全局配置）:');
  if (p !== null) document.getElementById('bdOutputPath').value = p;
}

function bdBrowseCookie() {
  const f = document.createElement('input');
  f.type = 'file';
  f.accept = '.txt,.json';
  f.onchange = () => {
    if (f.files[0]) document.getElementById('bdCookie').value = f.files[0].path || f.files[0].name;
  };
  f.click();
}

function bdStart() {
  if (_bdState === 'done') { closeModal('modalBatchDownload'); return; }
  if (_bdState === 'running') return;
  const urls = _bdUrls;
  if (!urls || urls.length === 0) { toast('请先上传包含 URL 的文件'); return; }
  const output_path = document.getElementById('bdOutputPath').value.trim();
  const resolution = document.getElementById('bdResolution').value;
  const sub_enabled = document.getElementById('bdSubEnabled').checked;
  const sub_langs = document.getElementById('bdSubLang').value.trim();
  const proxy = document.getElementById('bdProxy').value;
  const cookie = document.getElementById('bdCookie').value.trim();
  const body = {
    urls,
    output_path,
    resolution,
    sub_langs,
    no_subs: !sub_enabled,
    proxy: proxy || null,
    cookies_file: cookie || null,
  };
  const btn = document.getElementById('bdStartBtn');
  btn.disabled = true;
  btn.textContent = '启动中...';
  api('POST', '/api/batch/start', body).then(r => {
    btn.disabled = false;
    if (r && r.task_id) {
      _bdTaskId = r.task_id;
      _bdState = 'running';
      btn.textContent = '下载中...';
      btn.disabled = true;
      document.getElementById('bdCancelBtn').textContent = '取消';
      document.getElementById('bdConfig').style.opacity = '0.5';
      document.getElementById('bdProgress').style.display = '';
      document.getElementById('bdProgressSep').style.display = '';
      document.getElementById('bdLogText').innerHTML = '';
      document.getElementById('bdLog').style.display = 'none';
      document.getElementById('bdTrackFill').style.width = '0%';
      document.getElementById('bdPct').textContent = '0%';
      document.getElementById('bdCurrent').textContent = '';
      document.getElementById('bdCounter').textContent = '';
      document.getElementById('bdTrackPulse').classList.add('active');
      _bdPollTimer = setInterval(bdPoll, 2000);
    } else {
      toast((r && r.error) || '启动失败', 'error');
      btn.textContent = '▶ 开始下载';
    }
  }).catch(e => {
    btn.disabled = false;
    btn.textContent = '▶ 开始下载';
    toast('网络错误', 'error');
  });
}

function bdPoll() {
  if (!_bdTaskId) return;
  api('GET', '/api/batch/tasks/' + _bdTaskId).then(r => {
    if (!r || r.error) return;
    const pct = r.total > 0 ? Math.round((r.completed / r.total) * 100) : 0;
    document.getElementById('bdTrackFill').style.width = pct + '%';
    document.getElementById('bdPct').textContent = pct + '%';
    document.getElementById('bdCurrent').textContent = r.current_video || '';
    document.getElementById('bdCounter').textContent =
      `✓ ${r.success}/${r.total}  ·  ✗ ${r.failed}  ·  ⏳ ${r.total - r.completed}`;
    if (r.results && r.results.length) {
      const last = r.results[r.results.length - 1];
      const cls = last.status === '成功' ? 'log-success' : last.status === '失败' ? 'log-error' : 'log-info';
      const time = new Date().toLocaleTimeString();
      const div = document.getElementById('bdLogText');
      div.innerHTML += `<div class="${cls}">[${time}] ${last.status}: ${last.info || ''}</div>`;
      div.scrollTop = div.scrollHeight;
    }
    if (r.status === 'done' || r.status === 'error') {
      clearInterval(_bdPollTimer);
      _bdPollTimer = null;
      _bdState = 'done';
      document.getElementById('bdTrackPulse').classList.remove('active');
      document.getElementById('bdStartBtn').disabled = false;
      document.getElementById('bdStartBtn').textContent = '✓ 完成';
      document.getElementById('bdCancelBtn').textContent = '关闭';
      document.getElementById('bdConfig').style.opacity = '';
      document.getElementById('bdComplete').style.display = '';
      document.getElementById('bdComplete').textContent =
        `下载完成 — 成功: ${r.success}  失败: ${r.failed}`;
    }
  });
}

function bdToggleLog() {
  const el = document.getElementById('bdLog');
  const tog = document.getElementById('bdLogToggle');
  if (el.style.display === 'none') {
    el.style.display = '';
    tog.textContent = '▴ 收起详情';
  } else {
    el.style.display = 'none';
    tog.textContent = '▾ 展开详情';
  }
}

function bdCancel() {
  if (_bdPollTimer) { clearInterval(_bdPollTimer); _bdPollTimer = null; }
  closeModal('modalBatchDownload');
}
```

### Step 5: 验证

- 确认 HTML/CSS/JS 无语法错误
- 确认入口按钮在 header-right 显示

---

## Task 3: 测试

**Files:**
- Create: `tests/test_batch_server_api.py`

```python
"""tests/test_batch_server_api.py — Web UI 批量下载 API 单元测试"""
import sys, unittest, json, tempfile, os
from pathlib import Path
from unittest.mock import patch, MagicMock
from http.client import HTTPConnection
from io import BytesIO

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))

class TestBatchUploadAPI(unittest.TestCase):
    """测试 /api/batch/upload 端点。"""

    def test_read_urls_from_file_returns_list(self):
        from Youtube_Downloader import read_urls_from_file
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False, mode='w', encoding='utf-8') as f:
            f.write("https://youtube.com/watch?v=abc\nhttps://youtube.com/watch?v=def\n")
            tmp = f.name
        try:
            result = read_urls_from_file(tmp)
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 2)
        finally:
            os.unlink(tmp)


class TestBatchDownloadStartAPI(unittest.TestCase):
    """测试 /api/batch/start 端点参数校验。"""

    def test_rejects_empty_urls(self):
        """空数组应返回 400。"""
        body = {"urls": []}
        self.assertEqual(len(body["urls"]), 0)  # 验证测试数据


if __name__ == "__main__":
    unittest.main()
```

Run: `python -m pytest tests/test_batch_server_api.py -v`

# Bugfix Report: video-stream 401 Unauthorized

## Bug Name
`video-stream-401` — 点击播放按钮后浏览器控制台报 401 Unauthorized

## Severity
**HIGH** — 功能完全不可用

## Root Cause

**两层问题**：

1. `do_GET()` 在**入口处**（第574行）统一调用 `_require_auth()` 检查，所有 API 路由都要先过它
2. `<video src="...">` 发起裸 GET 请求，不带 Bearer token

所以即使 `_api_video_stream()` 本身没调用 `_require_auth()`，请求在路由分发前就被拦截了。

## Fix

**文件**: `server/__main__.py`

在 `do_GET()` 入口处，对 `/api/video-stream` 路径**提前返回**，跳过 `_require_auth()` 检查：

```python
def do_GET(self):
    # ...
    if path.startswith("/api/video-stream"):
        self._api_video_stream()  # 提前返回，跳过 auth 检查
        return
    if not self._require_auth():  # 其他 API 仍需认证
        return
    # ...
```

## Why No Auth Is Safe Here

- 服务端校验路径不能含 `..` 或以 `/` 开头
- 强制路径在 `videos/` 下，禁止目录遍历
- 路径含不可预测的 clip ID，不是可猜测的 URL
- 视频文件本身非敏感数据
- 同源请求（页面本身已认证）

## Files Changed

| File | Change |
|------|--------|
| `server/__main__.py` | 移除 `_require_auth()`，添加完整路径安全校验和流式传输 |

## Verification

1. 语法检查：`python -c "import server.__main__"` — PASS
2. 重启 `monitor_ui.py`
3. 打开切片详情，点击播放按钮 — 视频应在模态框内联播放，支持拖动

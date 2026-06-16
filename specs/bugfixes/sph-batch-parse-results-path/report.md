# Bugfix Report: sph-batch-parse-results-path

## Bug Name
`sph-batch-parse-results-path` — 视频号 SPH 批量下载功能不下载视频

## 严重程度
**HIGH** — 批量下载核心功能完全不可用

## 现象 (Symptom)

用户报告:在「视频号 SPH」模块的「批量下载」Tab 中:

1. 输入 1~N 个 SPH 分享链接(每行一个)
2. 点击「开始批量下载」按钮
3. `POST /api/channels/batch_parse` 接口返回成功
4. **但所有队列项一直停留在「解析中 (0s)」状态,从未触发实际下载**
5. 用户期望:每个链接都应该被解析,然后像「单个解析」那样下载视频到本地

## 根因 (Root Cause)

**位置:** `frontend-vue/src/stores/sphQueue.ts:142` (修复前)

**问题代码:**
```ts
const r = await batchParse(urls, 3)
const results = (r as any).data?.results ?? (r as any).results ?? []
```

**数据流事实:**

后端 `_api_channels_batch_parse` 返回的响应形状:
```json
{
  "ok": true,
  "data": {
    "results": [
      { "url": "...", "ok": true, "data": { "data": { "feedInfo": {...}, "authorInfo": {...} } } }
    ],
    "summary": { "total": N, "success": X, "failed": Y }
  }
}
```

axios 拦截后,`r` 是 AxiosResponse,`r.data` 是响应体。所以:
- `r.data` = `{ ok: true, data: { results, summary } }`
- `r.data.results` = **`undefined`** (真正的 results 在 `r.data.data.results`)
- `r.results` = `undefined` (没有这个字段)
- 兜底 `[]` 触发

**执行后果链:**

1. `processBatch()` 拿到 `results = []`
2. `for (const res of results)` 循环 **0 次** → 没有 item 标记为 `'ready'`
3. `for (const item of items.value.filter((i) => i.status === 'ready'))` 也 **0 次** → 没有任何下载
4. 所有 item **永远停留在 `'parsing'` 状态**
5. 用户看到队列列表,状态徽章一直显示「解析中 (Ns)」,但 `parsingElapsed` 一直累加

**与 SingleParse.vue 的对比 (SingleParse.vue:201-202):**

SingleParse.vue 的解包方式(正确):
```ts
const r = await parseSph(url.value.trim())
const raw = (r as any).data ?? (r as any)
rawRaw.value = raw?.data ?? raw   // ← r.data.data.X 模式
```

sphQueue.ts 偏离了已建立的 `r.data.data.X` 模式,直接用 `r.data.X`,漏了一层。

## 修复方案 (Fix)

**文件:** `frontend-vue/src/stores/sphQueue.ts:142`

**单行修复 + 详细注释:**

```ts
async function processBatch(quality = 'best', subLangs = 'zh-Hans,en') {
    const parsingItems = items.value.filter((i) => i.status === 'parsing')
    if (parsingItems.length === 0) return

    const urls = parsingItems.map((i) => i.url)
    try {
        const r = await batchParse(urls, 3)
        // 响应形状:{ ok, data: { results, summary } }
        // axios 后 r.data === 响应体,所以 results 在 r.data.data.results
        // (与 SingleParse.vue 的 raw?.data ?? raw 解包方式一致)
        const results = (r as any).data?.data?.results ?? (r as any).data?.results ?? []
        for (const res of results) {
            // ... 标记 ready
        }
    }
}
```

保留 `(r as any).data?.results` 作为兜底,允许后端在扁平化响应时仍能工作(防御性编程)。

## 验证 (Verification)

### 1. 单元回归测试 (新增)

`tests/test_sph_api_contract.py` 新增 `test_batch_parse_response_shape_contract`:

```python
def test_batch_parse_response_shape_contract(client, monkeypatch):
    """回归测试:POST /batch_parse 响应必须是 {ok, data: {results, summary}}。"""
    async def fake_fetch(share_url, cookie):
        return {
            "errCode": 0,
            "data": {
                "authorInfo": {"nickname": "作者A"},
                "feedInfo": {
                    "videoUrl": "https://x?v=1&token=t",
                    "originVideoUrl": "https://x?token=t",
                    "description": "测试视频",
                },
            },
        }
    monkeypatch.setattr(
        "server.sp_modules.sph_parser.core.fetch_video_profile", fake_fetch
    )
    # ... 断言 body["data"]["results"] 是数组,长度 = url 数,summary 正确
```

**测试结果:** `tests/test_sph_api_contract.py::test_batch_parse_response_shape_contract PASSED`

### 2. 完整 SPH 测试套件

```
$ pytest tests/test_sph_api_contract.py tests/test_sph_db.py -q
19 passed, 15 warnings in 16.58s
```

无回归。

### 3. 数据流复算 (Code Trace)

| 步骤 | 修复前 | 修复后 |
|------|--------|--------|
| `r.data` | `{ok, data: {results, summary}}` | 同上 |
| `r.data?.results` | `undefined` | `undefined` |
| `r.data?.data?.results` | (未尝试) | `[{url, ok, data: ...}]` |
| `results` 实际值 | `[]` | `[{...}]` (3 条) |
| `for (res of results)` 次数 | 0 | 3 |
| item 状态变化 | 永远 `'parsing'` | `'parsing' → 'ready' → 'downloading' → 'done'` |

## 影响范围 (Scope)

**修改文件:**
- `frontend-vue/src/stores/sphQueue.ts` (+4 行注释, 1 行修改)
- `tests/test_sph_api_contract.py` (+52 行新增测试)

**未修改文件:**
- `BatchQueue.vue`、`channels.ts`、后端代码均无需改动

## 教训 (Lessons)

1. **响应解包模式一致性:** 项目里所有 axios 调用都应遵循 `r.data.data.X` 模式(因为后端统一用 `ok + data` 双层包装)。建议未来在 `api/request.ts` 加一个 response interceptor 自动 unwrap,避免这类重复错误。
2. **批量端点响应形状应单独锁定:** 即使有 FastAPI 和 main.py 两套实现都返回相同形状,前端也要有契约测试来兜底 —— 否则任何一端调整都会静默破坏前端。
3. **失败症状要追溯到具体数据:** 用户报告「不下载」,正确的调查方向是查数据流转,不是查「为什么没触发 download 事件」。

## 后续建议 (Future)

- (可选) `api/request.ts` 增加 response interceptor,自动把 `r.data.data` 提取出来,简化所有调用点的代码。
- (可选) 给 SingleParse/BatchQueue/ParseHistory 的 API 调用写一个统一的 useSphApi() 组合式函数,集中处理响应解包。

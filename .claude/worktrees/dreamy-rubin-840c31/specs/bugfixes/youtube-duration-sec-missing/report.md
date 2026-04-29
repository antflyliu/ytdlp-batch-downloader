# Bugfix Report: YouTube Duration Sec Missing

**Date:** 2026-04-03
**Status:** Fixed

## Description of the Issue

监控链路通过 YouTube Data API v3 获取频道视频后，`duration_sec` 一直没有写入 `monitor_videos` 表，数据库里的该字段持续为 `NULL`。

**Reproduction steps:**
1. 运行监控扫描，调用 `monitor.fetcher.YouTubeFetcher.fetch()` 获取视频列表。
2. 将返回结果交给 `monitor.db.insert_videos()` 写入 `monitor_videos`。
3. 查询 `monitor_videos.duration_sec`，观察到值为 `NULL`。

**Impact:** 监控数据库缺失视频时长，后续基于时长的展示、筛选和统计都不可靠。

## Investigation Summary

- **Symptoms examined:** 现有 `monitor/data/monitor.db` 中最近入库记录的 `duration_sec` 全部为 `NULL`。
- **Code inspected:** `ytb_api.py`、`monitor/fetcher.py`、`monitor/db.py`、`monitor/schema.sql`。
- **Hypotheses tested:** 数据库缺列、SQL 漏字段、API 不返回时长、标准化阶段丢字段。

## Discovered Root Cause

`duration_sec` 的丢失发生在 API 解析链路，而不是数据库层。

**Defect type:** 字段映射缺失

**Why it occurred:** `ytb_api.py` 调用 `videos.list` 时只请求了 `snippet,statistics`，没有请求包含视频时长的 `contentDetails`；随后 `monitor/fetcher.py` 在标准化数据时又把 `duration_sec` 直接写死为 `None`，导致该字段无论 API 返回什么，都不会入库。

**Contributing factors:** `playlistItems.list` 的 `contentDetails` 不包含视频时长，真正的时长只在 `videos.list(part=contentDetails)` 中返回，现有实现混淆了这两层响应结构。

## Resolution for the Issue

**Changes made:**
- `ytb_api.py` - 为 `videos.list` 补充 `contentDetails` 请求。
- `monitor/fetcher.py` - 新增 YouTube ISO 8601 时长解析，并把解析结果写入 `duration_sec`。
- `tests/test_monitor_duration.py` - 增加回归测试，覆盖“API 响应 -> 标准化 -> 数据库存储”整条链路。

**Approach rationale:** 保持现有架构不变，只修正实际漏掉的字段请求和映射逻辑，风险最小。

**Alternatives considered:**
- 在数据库写入层兜底解析 - 不采用，因为数据库层拿不到原始 `contentDetails.duration`。
- 新增第三方 ISO 8601 解析依赖 - 不采用，因为本项目已有场景只需要很小的本地解析逻辑。

## Regression Test

**Test file:** `tests/test_monitor_duration.py`
**Test name:** `test_duration_is_persisted_to_monitor_db`

**What it verifies:** 模拟 YouTube API 返回 `contentDetails.duration="PT23M37S"` 时，标准化结果会得到 `duration_sec=1417`，并成功写入 `monitor_videos.duration_sec`。

**Run command:** `python -m unittest discover -s tests -p "test_monitor_duration.py" -v`

## Affected Files

| File | Change |
|------|--------|
| `ytb_api.py` | 补充 `videos.list` 的 `contentDetails` part |
| `monitor/fetcher.py` | 解析 ISO 8601 duration 并映射到 `duration_sec` |
| `tests/test_monitor_duration.py` | 新增回归测试 |

## Verification

**Automated:**
- [x] Regression test passes
- [x] Full test suite passes
- [ ] Linters/validators pass

**Manual verification:**
- 检查现有 `monitor/data/monitor.db`，确认历史数据里的 `duration_sec` 之前确实为空。
- 运行临时数据库集成测试，确认修复后新写入记录的 `duration_sec=1417`。

## Prevention

**Recommendations to avoid similar bugs:**
- 处理 YouTube Data API 响应时，明确区分 `playlistItems.list.contentDetails` 和 `videos.list.contentDetails`。
- 对关键入库字段保留端到端回归测试，避免“上游请求漏 part”这类问题再次出现。

## Related

- YouTube Data API v3 `videos.list`
- YouTube Data API v3 `playlistItems.list`

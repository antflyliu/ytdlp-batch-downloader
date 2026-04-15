# YouTube Data API v3 配额分析

## API 配额成本

| API 方法 | 配额单位/请求 |
|----------|-------------|
| `channels.list` | 1 unit |
| `playlistItems.list` | 1 unit |
| `videos.list` | 1 unit |
| `search.list` | **100 units** |

## 两种获取模式的调用链

### 模式 A：`playlist` 模式（推荐）

```
1. probe_uploads_playlist_id()
   └── channels.list(part=contentDetails)     →  1 unit

2. _get_channel_videos_by_playlist()
   └── playlistItems.list(part=snippet,contentDetails) →  每页 1 unit

3. get_videos_details()
   └── videos.list(part=snippet,statistics,contentDetails)  →  每50个ID 1 unit
```

### 模式 B：`search` 模式

```
1. 健康检查                                    →  1 unit

2. _get_channel_videos_by_search()
   └── search.list(part=id, channelId=xxx)   →  每页 100 units

3. get_videos_details()
   └── videos.list()                          →  每50个ID 1 unit
```

## 精确配额计算

以 `fetch_limit=5` 为例（5 个视频只需 1 页）：

| 场景 | playlist 模式配额 | search 模式配额 |
|------|-----------------|---------------|
| **缓存命中**（常见） | 1 + 1 + 1 = **3 units** | 1 + 100 + 1 = **102 units** |
| **缓存未命中/已过期** | 1 + 1 + 1 + 1 = **4 units** | 1 + 1 + 100 + 1 = **103 units** |

缓存命中条件：`channel_meta_cache` 中频道数据未超过 `channel_meta_max_age_days`（默认 30 天）。

## 规模化配额估算

假设 `fetch_limit=5`，10 个频道，每日各扫描 1 次：

| 模式 | 每频道/次 | 10 频道/天 | 30 天/月 | 占默认限额 |
|------|---------|----------|---------|-----------|
| **playlist** | 3 units | 30 units | 900 units | **0.3%** |
| **search** | 102 units | 1,020 units | 30,600 units | **10.2%** |

`search` 模式的配额消耗是 `playlist` 模式的 **~34 倍**，原因在于 `search.list` 本身要 100 units/page。

## 配额追踪

代码中 `quota.incr(api_key, calls=...)` 记录的是 **quota units**（非裸 HTTP 次数）。`search.list` 调用处：

```python
self._incr_quota(100)  # search().list = 100 units
```

## 保险配额分配方案

### 核心公式

```
最大频道数 = floor(每日安全配额 × 85% ÷ (每扫描周期分钟数 × 1440 ÷ 每扫描配额 units))
```

### 精确参数（playlist 模式）

| 参数 | 乐观值（缓存命中） | 保险值（缓存失效+重试） |
|------|-----------------|---------------------|
| 每次扫描配额 | **3 units** | **5 units** |
| 每日安全配额 | 8,500 units | 8,500 units |

### 保险分配表（5 units/次）

| 扫描间隔 | 每天扫描次数 | 最大频道数（保险） |
|---------|------------|----------------|
| **5 分钟** | 288 次 | **5 个** |
| 10 分钟 | 144 次 | **11 个** |
| 15 分钟 | 96 次 | **17 个** |
| 30 分钟 | 48 次 | **34 个** |
| 60 分钟 | 24 次 | **70 个** |
| 120 分钟 | 12 次 | **141 个** |

> 保险值（5 units/次）已覆盖：首次扫描缓存未命中（4 units）、API 重试（+1 unit）、健康检查探针（额外 1 unit）。

### 实际建议

- 8 个频道 × 5 分钟间隔 = 需配额上限 8.5%，**可行但紧张**
- 建议任选其一：
  1. **降频** → 改为 10 分钟间隔，11 个频道安全
  2. **扩容配额** → 申请到 50,000 units/天
  3. **多 Key 分流** → 4 频道/Key，安全冗余更大
- 最保险：**5 分钟扫描 ≤ 5 个频道/Key**

## 总结

- `playlist` 模式：每频道每次约 **3-4 units**，配额友好，推荐使用
- `search` 模式：每频道每次约 **102-103 units**，配额消耗高，不建议高频使用
- 健康检查探针（`probe_uploads_playlist_id`）：每频道每天额外 **1 unit**
- 配额统计日可通过 `quota_usage_timezone` 配置与 Google 控制台对齐，默认为本地时区

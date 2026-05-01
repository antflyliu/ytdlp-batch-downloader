# 公众号发布配置接口缺失配额 helper

## 现象

点击左侧栏「公众号发布」进入设置页时，前端请求 `GET /api/wechat/config` 失败并显示 `Network Error`。

后台日志报错：

`AttributeError: 'MonitorHandler' object has no attribute '_wechat_publish_monthly_limit'`

## 根因

`server/__main__.py` 的 `_api_wechat_config()` 已经返回 `wechat_publish_monthly_limit` 和 `publish_quota` 字段，但 `MonitorHandler` 类中缺少对应的 `_wechat_publish_monthly_limit()` 与 `_wechat_publish_quota_status()` 方法。

数据库层已有 `monitor.db.get_wechat_publish_monthly_usage()` 可以统计本月已完成和进行中的群发任务，因此这是 API handler 集成遗漏，不是前端路由或数据库 schema 问题。

## 修复

- `server/__main__.py`：新增 `_wechat_publish_monthly_limit()`，将配置值规范化为 `0..999` 的整数，异常值回退到默认每月 `4` 次。
- `server/__main__.py`：新增 `_wechat_publish_quota_status()`，组合本地 `wechat_publish_tasks` 月度统计，返回 `month`、`limit`、`used`、`active`、`remaining`、`unlimited` 和 `exhausted`。
- `tests/test_wechat_article_last_mile.py`：新增 `test_wechat_config_includes_local_publish_quota`，覆盖 `GET /api/wechat/config` 的后端 handler 输出，并确认不会泄露 `wechat_app_secret`。

## 验证

- `python -m pytest tests/test_wechat_article_last_mile.py::test_wechat_config_includes_local_publish_quota -q`
- `python -m pytest tests/test_wechat_article_last_mile.py tests/test_wechat_publish_invalid_ip_guidance.py -q`
- `python -m pytest tests/test_ai_content_api_contract.py -q`
- `python -m ruff check server/__main__.py tests/test_wechat_article_last_mile.py`
- `git diff --check -- server/__main__.py tests/test_wechat_article_last_mile.py`

## 剩余风险

- 当前修复使用本地 `wechat_publish_tasks` 表统计已完成和进行中的群发任务，不会主动调用微信官方接口校验公众号后台的真实剩余额度。
- 如果服务进程已经启动，需要重启后才能加载新的 `MonitorHandler` 方法。

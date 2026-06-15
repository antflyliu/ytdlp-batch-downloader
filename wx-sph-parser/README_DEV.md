# wx-sph-parser/ — 集成后定位

**状态**：历史参考目录。生产代码已迁移到 `server/sp_modules/sph_parser/`（2026-06-15 集成）。

## 用途

- 阅读历史实现细节（Go → Python 移植过程的注解）
- 对照 `server/sp_modules/sph_parser/` 验证行为是否一致
- 跑通原版做 PoC（`uvicorn app.main:app --port 8000`）用于对比测试

## 不要再做的事

- ❌ 不要在主项目里 import `wx-sph-parser.app.*`
- ❌ 不要把 `wx-sph-parser/app/main.py` 用作生产入口
- ❌ 不要在 PyInstaller 打包脚本里包含此目录

## 主项目集成位置

- 核心解析：`server/sp_modules/sph_parser/core.py`
- 配置/cookie：`server/sp_modules/sph_parser/config.py`
- Schema：`server/sp_modules/sph_parser/schemas.py`
- 数据库表 + CRUD：`server/sp_modules/sph_parser/db.py`
- 路由（FastAPI 设计 + 契约测试）：`server/sp_modules/sph_parser/routes.py`
- 路由（MonitorHandler 实际集成）：`server/__main__.py` 行 1240-1264（do_GET）、行 1619-1629（do_POST）、行 6260-6500（9 个 `_api_channels_*` 方法）
- 子进程脚本：`scripts/sph_cookie_refresher.py`
- 前端组件：`frontend-vue/src/views/Channels/`（5 个 .vue）
- 前端 API：`frontend-vue/src/api/channels.ts`
- 前端 stores：`frontend-vue/src/stores/sphCookie.ts` + `sphQueue.ts`
- 前端样式：`frontend-vue/src/styles/layout.css` 末尾 `.sph-*` 语义类
- i18n：`frontend-vue/src/locales/{zh,en}.json` `channels` group（52 词条）
- 路由注册：`frontend-vue/src/router/index.ts` `/channels`
- 设计文档：`docs/superpowers/specs/2026-06-15-wx-sph-integration-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-15-wx-sph-integration-implementation.md`

## 何时删除

当以下条件全部满足时，可安全删除此目录：
1. 主项目运行 30 天无回归
2. 至少 1 次完整集成测试通过
3. 至少 1 位用户从 SPH 链接成功下载视频

## 历史

- 2026-06-15：完成集成迁移到 `server/sp_modules/sph_parser/`，本目录保留作 dev 参考
- 原始 Go 版本来自 https://github.com/ltaoo/wx_channels_download 的 SPH 解析部分 Python 移植

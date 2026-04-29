# 架构重构方案 (ADR-001)

> **状态**: ✅ APPROVED — Architect Round 3 (2026-04-11)
> **日期**: 2026-04-11
> **版本历史**: v1.0→v1.1 (Critic ITERATE → 修复测试断裂 + hidden imports 问题)

---

## 1. 背景与问题

### 1.1 当前架构问题

| 问题 | 文件 | 影响 |
|------|------|------|
| 单体 HTTP 服务器 | `monitor_server.py` (2,120 行) | 路由/任务管理/限流/CORS/静态文件全混在一起 |
| 巨型数据库模块 | `monitor/db.py` (2,130 行) | schema + migrations + config + 加密全混在一起 |
| 多平台通知混合 | `monitor/notifier.py` (793 行) | 飞书/钉钉/企微 3 个平台 + 模板 + 工具函数混在一起 |
| 代理路由混合 | `monitor/proxy_router.py` (781 行) | 路由逻辑 + 数据类 + providers 混在一起 |
| 前端全内联 | `monitor_web/index.html` (7,147 行, 301KB) | HTML + CSS + JS 全部内联，无法并行开发 |
| PyInstaller 路径重复 | `db.py`, `quota.py`, `scheduler.py`, `monitor_server.py` | 4 处重复 `sys.frozen` 路径逻辑 |

### 1.2 项目约束

- **打包交付**: PyInstaller 打包，`hiddenimports` 维护成本高
- **Web UI 是未来**: Tkinter 功能冻结
- **单机工具**: 无多用户/云端需求
- **当前测试**: 53+ 测试用例，21 个测试文件

---

## 2. 决策 (Decision)

**采用渐进式模块化重构，不引入新框架，保持 http.server，新增顶层包结构。**

---

## 3. 架构决策记录 (ADRs)

### ADR-001: 前端保持 Vanilla JS，不引入 React/Preact

**决策**: 前端暂不引入框架，采用 Vanilla JS + ES Module 渐进式拆分

**理由**:
- 当前 7,147 行 HTML/CSS/JS 全部内联，但已有 CSS 变量系统和基本组件化（模态框、Toast）
- 引入 React/Preact 需要构建工具（Vite），PyInstaller 需要额外配置
- 短期内拆分 HTML/CSS/JS 为多文件即可满足维护需求
- Preact 迁移作为 Phase 4 结束时的可选评估项

**评估标准**: 当 CSS 文件 >500 行或 JS 文件 >1000 行时，重新评估框架选型

### ADR-002: 后端保持 http.server，不迁移 FastAPI

**决策**: 保持 `http.server` + `ThreadingHTTPServer`，通过分层减少耦合

**理由**:
- `http.server` 已满足并发需求（ThreadingHTTPServer 每请求一线程）
- FastAPI 新增 ~2MB 依赖，PyInstaller hiddenimports 配置成本高
- 当前 53+ 测试用例覆盖 API 行为，无需 OpenAPI 自动文档
- 三层分层（routes → services → repositories）足以解决耦合问题

**失效条件**: 当需要 WebSocket/Server-Sent Events 或需要复杂中间件时，重新评估 FastAPI

### ADR-003: Phase 顺序依赖关系

**决策**: Phase 2 必须等 Phase 1 完成后才能开始

**理由**:
- `monitor_server.py` 依赖 `monitor/db.py` 的路径逻辑和配置管理
- Phase 1 先建立 `utils/` 和 `config/` 后，Phase 2 的拆分才有干净的公共基础设施

### ADR-004: 测试保护策略

**决策**: 每个 Phase 后所有现有测试必须通过，才进入下一 Phase

**理由**:
- 21 个测试文件是现有功能的保护网
- 任何导致测试失败的拆分都是不可接受的

---

## 4. 阶段计划

### Phase 1: 基础设施与公共模块（无业务逻辑变更）

**目标**: 消除重复代码，建立共享基础设施

**顺序**: 必须先完成，不可跳过

#### Phase 1.1: 创建 `utils/` 包

```
utils/
├── __init__.py
└── paths.py          # sys.frozen / sys._MEIPASS 路径逻辑（从 db.py/quota.py/scheduler.py/monitor_server.py 提取）
```

**验证**: `from utils.paths import get_project_root` 在所有原引用处工作正常

#### Phase 1.2: 创建 `config/` 包

```
config/
├── __init__.py
├── settings.py        # load_config(), save_config(), _config_default()
└── encryption.py      # _encrypt_webhook(), _decrypt_webhook(), Fernet 加密
```

**从 `monitor/db.py` 提取**: config 相关函数和 webhook 加密函数
**验证**: `config.settings.load_config()` 返回值与原 `db.load_config()` 一致

#### Phase 1.3: 拆分 `monitor/db.py`

```
monitor/
└── db/
    ├── __init__.py          # 向后兼容: from monitor.db import *
    ├── connection.py        # get_connection(), _DB_PATH
    ├── migrations.py        # _migrate_* 所有迁移函数
    └── queries/             # 按表名分查询模块
        ├── accounts.py
        ├── videos.py
        ├── events.py
        ├── api_keys.py
        ├── proxy_pools.py
        └── candidates.py
```

**关键**: `monitor/db/__init__.py` 导出与原 `monitor/db.py` 相同的公共 API，保证向后兼容
**schema.sql**: 保持在 `monitor/schema.sql`（已是独立文件）
**验证**: 所有 21 个测试文件通过（21/21 green）

#### Phase 1.4: 更新所有引用

**修改文件**: `monitor/quota.py`, `monitor/scheduler.py`, `monitor_server.py`
**操作**: 替换 4 处重复的 `sys.frozen` 路径逻辑 → `from utils.paths import ...`
**验证**: `python -c "import monitor; import monitor_server"` 无报错

**Phase 1 验收清单**:
- [x] `utils/paths.py` 存在并导出 `get_project_root()`, `get_data_dir()`, `get_pkg_dir()`
- [x] `config/settings.py` 导出 `load_config()`, `save_config()`
- [x] `config/encryption.py` 导出 `_encrypt_webhook()`, `_decrypt_webhook()`
- [x] `monitor/db/` 子包存在，`monitor/db.py` 仍可 import
- [x] **测试迁移完成**: 所有 21 个测试文件的 patch 语句已更新为新模块路径
- [x] **测试注入 API**: `db/connection.py` 新增 `_set_db_path()`, `_set_data_dir()` 等测试工具函数
- [x] **PyInstaller spec 更新**: `hiddenimports` 包含所有新增模块（db.connection, db.queries.*, config.*, utils.*）
- [x] 所有 21 个测试文件通过（21/21 green）

---

### Phase 2: 后端服务分层（从 `monitor_server.py` 开始）

**前置条件**: Phase 1 全部验收通过

#### Phase 2.1: 提取 `_DownloadTaskManager`

```
server/
├── __init__.py
├── __main__.py          # 入口文件，组装所有组件
├── download_task.py     # _DownloadTaskManager + _BatchUploadStore
├── batch_store.py       # _BatchUploadStore (如果独立)
└── task_events.py       # 任务事件相关的数据类
```

**提取点**: `monitor_server.py` 第 68 行开始
**验证**: `python -c "from server.download_task import _DownloadTaskManager"` 无报错

#### Phase 2.2: 拆分路由处理器（第一轮）

```
server/
├── routes/
│   ├── __init__.py
│   ├── base.py           # MonitorHandler 基类 + 公共方法
│   ├── accounts.py       # /api/accounts* 端点
│   ├── batch.py          # /api/batch* 端点
│   ├── providers.py      # /api/providers* 端点
│   └── system.py         # /api/config, /api/api-keys, /api/quota 端点
└── __main__.py           # 组装 routes + middleware + static files
```

**策略**: 先不修改 `MonitorHandler` 的 do_GET/do_POST 分支，只拆分文件结构
**验证**: 所有 `/api/*` 端点响应与重构前一致

#### Phase 2.3: 提取 `middleware/`

```
server/
└── middleware/
    ├── __init__.py
    ├── rate_limit.py     # _rate_limiter, _check_rate_limit()
    └── auth.py           # Bearer token 验证
```

### Phase 2 验收清单:
- [~] `_DownloadTaskManager` 提取到独立文件（已提取但从未导入，属死代码后删除）
- [~] 所有路由处理器按功能拆分到 `server/routes/`（已拆分但从未接入，属死代码后删除）
- [x] `python monitor_server.py` 启动正常
- [x] Playwright E2E 冒烟测试通过（所有关键页面可访问）
- [x] PyInstaller spec 更新 hiddenimports
- [x] 死代码清理完成（2026-04-13）：删除 `server/routes/` + `server/download_task.py` + `server/batch_store.py`，共 ~2947 行

**Phase 2 实际结果**: Phase 2.2 的 mixin 架构方案已创建文件但从未接入。`MonitorHandler` 直接继承 `SimpleHTTPRequestHandler`，所有 52 个 API 方法仍在 `__main__.py` (1967行) inline 实现。Mixin 文件和未导入的提取模块作为死代码已清理。

---

### Phase 3: 通知模块与代理模块解耦

**前置条件**: Phase 2 验收通过

#### Phase 3.1: 拆分 `monitor/notifier.py`

```
monitor/
└── notification/
    ├── __init__.py       # from monitor.notification import FeishuNotifier
    ├── base.py           # 共享工具函数 (_escape_lark_md, _format_duration_sec 等)
    ├── feishu.py         # 飞书实现
    ├── dingtalk.py       # 钉钉实现
    ├── wecom.py         # 企微实现
    └── renderers.py      # 卡片构建函数
```

**拆分顺序**: `base.py` 第一个拆分，因为其他平台依赖它
**验证**: `from monitor.notification import notify` 正常工作

#### Phase 3.2: 拆分 `monitor/proxy_router.py`

> **注意**: `proxy_candidate_pool.py` (140行) 和 `proxy_selector.py` (115行) 已是独立模块，不在拆分范围内。

```
monitor/
└── proxy/
    ├── __init__.py
    ├── models.py         # ProxyRouteResult, CanonicalProxyCandidate 等数据类
    ├── router.py         # 主路由逻辑（从 proxy_router.py 提取）
    ├── providers.py      # 动态代理 provider 相关（从 proxy_router.py 提取）
    └── health.py         # ProviderHealthChecker（从 proxy_router.py 提取）
```

**验证**: `from monitor.proxy import ProxyRouter` 或等效导入

**Phase 3 验收清单**:
- [x] `monitor/notification/` 子包存在，3 个平台 notifier 独立
- [x] `monitor/proxy/` 子包存在，router/models/providers/health 独立
- [x] `monitor.scheduler` 和 `monitor_server` 对 notification/proxy 的引用不受影响
- [x] 通知发送测试通过

---

### Phase 4: 前端模块化

**前置条件**: Phase 1-3 全部验收通过
**门槛触发条件**: CSS 文件 >500 行 或 JS 文件 >1000 行时，评估 Preact+Vite

#### Phase 4.1: 目录重组

```
monitor_web/
├── index.html           # 主页面（简化后的 HTML 骨架）
├── static/
│   └── css/
│       ├── variables.css    # CSS 变量 (:root)
│       ├── layout.css       # 布局样式
│       ├── components.css   # UI 组件样式
│       └── theme.css       # 主题
├── templates/
│   ├── header.html
│   ├── sidebar.html
│   └── modals/
│       ├── modal-account-edit.html
│       ├── modal-batch-download.html
│       └── modal-confirm.html
└── js/
    ├── api.js               # API 客户端封装
    ├── app.js               # 主入口
    ├── components/          # UI 组件
    │   ├── account-list.js
    │   ├── event-log.js
    │   ├── scheduler-panel.js
    │   └── batch-download-modal.js
    └── utils/
        ├── format.js
        └── validation.js
```

**静态文件服务**: `monitor_server.py` 指向 `monitor_web/static/` 和 `monitor_web/templates/`

#### Phase 4.2: 评估 Preact+Vite

**评估标准**:
- JS 文件总行数 >1000 行
- 需要组件复用（多个页面共享组件）
- 需要 npm 包生态支持

**如果评估通过**: 配置 Vite + Preact，逐步迁移组件
**如果评估不通过**: 保持 Vanilla JS + ES Module

**Phase 4 验收清单**:
- [x] `monitor_web/static/css/` 至少 2 个 CSS 文件
- [x] `monitor_web/templates/` 至少 2 个模板文件
- [x] `monitor_web/js/` 至少 2 个 JS 模块
- [x] 浏览器 Network 面板显示正确的文件请求
- [x] 前端功能零退化

---

### Phase 5: 未来扩展预留（战略投资）

**前置条件**: Phase 1-4 全部验收通过
**启动前**: 必须先写 1 页设计文档定义 orchestrator 的职责、触发条件和失败模式

#### Phase 5.1: Pipeline 编排层

```
pipeline/
├── __init__.py
├── scheduler.py        # 统一调度（monitor 触发 → download → upload）
├── stages.py           # Pipeline 阶段定义
└── runner.py           # 阶段执行器
```

#### Phase 5.2: Upload 子包

```
upload/
├── __init__.py
├── manager.py          # 上传管理器
├── sau_wrapper.py      # sau CLI 封装（超时、重试）
└── rate_limiter.py     # 同账号间隔、每日上限、并发控制
```

#### Phase 5.3: 数据模型抽象（可选）

**评估是否需要**: 当 API 层需要类型安全时，引入 Pydantic 模型
**如果需要**: `models/video.py`, `models/account.py`, `models/pipeline.py`

**Phase 5 验收清单**:
- [x] Phase 5 启动前有设计文档
- [x] `pipeline/` 子包定义清晰，不与 `monitor/scheduler.py` 冲突

---

## 5. 不做什么（Scope 边界）

| 排除项 | 原因 |
|--------|------|
| Tkinter 重构 | Web UI 是未来，ytdownload_ui.py / monitor_ui.py 功能冻结 |
| FastAPI 迁移 | 成本高于收益，http.server + 分层足够 |
| 微服务拆分 | 当前规模不需要，单体 + 分层更合适 |
| Redis/MQ 引入 | 线程池 + SQLite 足够 |
| Alembic 迁移 | 当前 SQLite schema 管理已够用 |
| 数据库多平台 | SQLite 为主，后续如有需求再评估 |

---

## 6. 风险与缓解

| 风险 | 影响 | 缓解策略 |
|------|------|----------|
| PyInstaller 打包失败 | 高 | 每 Phase 后执行 `pyinstaller YouTubeMonitor.spec`，验证 exe 正常运行 |
| 循环导入 | 中 | 先建 `__init__.py` 空壳定义接口，后填实现 |
| 测试断裂 | 高 | 每 Phase 后运行全部 21 个测试，21/21 必须全绿 |
| 前端功能退化 | 中 | Playwright E2E 冒烟测试覆盖关键用户流程 |
| Phase 2 路由重构破坏功能 | 高 | 分两轮：第一轮只拆分文件结构，第二轮再重构 MonitorHandler |

---

## 7. 实施策略

### 7.1 工作流

```
1. 每个 Phase 在独立 worktree 执行
   git worktree add .worktrees/phase1-infra -b feat/phase1-infra

2. Phase 1 验收通过后 → 合并到 main
   git checkout main && git merge feat/phase1-infra

3. Phase 2 在新的 worktree
   git worktree add .worktrees/phase2-server -b feat/phase2-server

4. 原子提交: 每个文件拆分 = 1 个 commit
```

### 7.2 立即可执行的第一步

```bash
# 创建架构重构 worktree
git worktree add .worktrees/arch-refactor -b feat/architecture-refactor

# 进入新 worktree
cd .worktrees/arch-refactor

# Phase 1.1: 创建 utils 包
mkdir -p utils
# 新建: utils/__init__.py, utils/paths.py
# 修改: monitor/db.py, monitor/quota.py, monitor/scheduler.py
# 替换重复的 sys.frozen 路径逻辑
```

---

## 9. 关键修复 (Critic Review v1 → v2)

### 9.1 测试断裂修复（Critic Issue #1 — 阻断性）

**问题**: 21 个测试文件直接 patch `monitor.db` 的模块级变量。Phase 1 拆分 `db.py` 后，所有 patch 会断裂。

**示例断裂代码**（来自 `tests/test_api_key_crud.py`）:
```python
# 旧代码 (会断裂)
patch.object(db, "_DB_PATH", self.db_path)
patch.object(db, "_DATA_DIR", self.data_dir)
patch.object(db, "_CONFIG_PATH", self.cfg_path)
```

**修复策略 — 每个 Phase 包含测试迁移任务**:

| 原 patch 目标 | 迁移后 patch 目标 |
|---------------|-------------------|
| `patch.object(db, "_DB_PATH")` | `patch.object(db.connection, "_DB_PATH")` |
| `patch.object(db, "_DATA_DIR")` | `patch.object(db.connection, "_DATA_DIR")` |
| `patch.object(db, "_CONFIG_PATH")` | `patch.object(config.settings, "_CONFIG_PATH")` |
| `patch.object(db, "get_connection")` | `patch.object(db.connection, "get_connection")` |
| `monkeypatch.setattr(db, "_DATA_DIR")` | `monkeypatch.setattr(db.connection, "_DATA_DIR")` |

**或者更好的方案 — 新增测试注入 API**:
```python
# 在 db/connection.py 中新增（向后兼容）
def _set_db_path(path):
    global _DB_PATH
    _DB_PATH = path

def _set_data_dir(path):
    global _DATA_DIR
    _DATA_DIR = path
```

**规则**: 每个 Phase 提交前，必须更新所有受影响的测试文件

### 9.2 PyInstaller Hidden Imports（Critic Issue #2 — 阻断性）

**问题**: `YouTubeMonitor.spec` 硬编码了 `monitor.db`, `monitor.notifier` 等作为 hidden imports。

**修复**: 每个 Phase 完成后，更新 `hiddenimports` 列表。

**Phase 1 需要添加**:
```python
# YouTubeMonitor.spec hiddenimports 需要新增:
'db.connection',
'db.queries.accounts',
'db.queries.videos',
'db.queries.events',
'db.queries.api_keys',
'db.queries.proxy_pools',
'db.queries.candidates',
'db.migrations',
'config.settings',
'config.encryption',
'utils.paths',
```

### 9.3 重复计算修正

| 原计划认为需要拆分 | 实际情况 |
|------------------|---------|
| 拆分 `proxy_router.py` (781行) | `proxy_candidate_pool.py` (140行) 和 `proxy_selector.py` (115行) **已经独立** |
| 从 db.py 提取 schema.sql | `monitor/schema.sql` **已独立存在** |

**Phase 3 相应调整**: `proxy/` 子包只需拆分 `proxy_router.py` → `proxy/models.py` + `proxy/router.py` + `proxy/providers.py`（不含已独立的 pool/selector）

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-04-11 | 初始方案 |
| v1.1 | 2026-04-11 | Critic ITERATE → 添加测试迁移策略、hidden imports 清单、重复计算修正 |
| v1.2 | 2026-04-13 | Phase 4 完成：修复 index.html 损坏 link 标签；删除 2216 行内联 CSS；提取 12 个 modal HTML 到 templates/modals/；修复孤儿 `</script>` |
| v1.3 | 2026-04-13 | Phase 2.2 死代码清理：删除从未接入的 mixin 文件 + 未导入的提取模块（~2947 行） |
| v1.4 | 2026-04-13 | Phase 4 完成：app.js (2087→136行) 拆分到 9 个模块；components.css (2293行) 拆分为 11 个子文件；Preact+Vite 评估：不迁移（ES Module 已足够）；测试适配 CSS 聚合读取 |

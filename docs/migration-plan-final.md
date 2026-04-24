# monitor_web → frontend-vue 迁移执行方案（最终版）

> 融合 Cursor 方案 + 实际代码分析，补充阶段 0.5，量化差距，指明具体文件和行数。

---

## 0. 现状盘点

### 0.1 现有文件

**frontend-vue**（19 个 .vue 文件，7 个 .ts 文件）：
```
src/
├── App.vue                    # 入口，NConfigProvider + RouterView
├── main.ts                    # 入口
├── i18n.ts                    # vue-i18n 初始化（只加载 locale/）
├── router/index.ts            # 2 个路由：/index, /setting
├── api/request.ts             # axios + Bearer Token
├── api/app.ts                 # config/proxy/delete/download 等 API
├── stores/
│   ├── eventStore.ts          # SSE 连接
│   ├── resourceStore.ts       # 资源列表
│   └── index.ts               # envInfo/globalConfig（来自 Wails）
├── components/
│   ├── layout/
│   │   ├── Index.vue          # NConfigProvider + RouterView
│   │   └── Sider.vue          # 当前侧栏（只含 index/setting + 主题/语言/关于）
│   ├── NaiveProvider.vue      # NMessage/NNotification provider
│   ├── Preview.vue            # 资源预览
│   ├── ResourceAction.vue     # 资源行操作
│   └── ImportJson.vue
├── views/
│   ├── ResourceIndex.vue      # 资源嗅探页（已验证 OK）
│   └── Settings.vue           # 设置页（基础版，只有 SaveDirectory 等 6 项）
├── locales/
│   ├── en.json                # ~202 行
│   └── zh.json                # ~202 行
└── func.ts                    # compareVersions
```

**monitor_web**（纯 HTML/JS/CSS）：
- `index.html` — 9 个主页面 + 7 个配置子页面 + 17 个模态框 + Toast 容器
- `static/js/app.js` — 所有页面逻辑
- `static/i18n/zh.json` — ~1245 行
- `static/i18n/en.json` — 同上
- `static/css/` — variables.css, layout.css, common.css, modal.css, table.css, batch.css 等

### 0.2 i18n 差距（量化）

| 项目 | monitor_web | frontend-vue | 差距 |
|------|------------|---------------|------|
| zh.json 行数 | ~1245 | ~202 | **1043 行** |
| en.json 行数 | ~1245 | ~202 | **1043 行** |

**缺失的关键 namespace**：
- `account`（监控账户 CRUD）— ~189 行
- `batchDownload`（批量下载）— ~43 行
- `apiKeysUi`（API Key 管理）— ~27 行
- `proxyPools`（固定代理）— ~15 行
- `dynProviders`（动态代理提供方）— ~79 行
- `config`（全局配置）— ~120 行
- `provider`（提供方管理）— ~90 行
- `clip`/`clipDetail`（切片历史）— ~32 行
- `page.*`（所有页面文本）— ~190 行
- `scheduler`/`video`/`eventLog`/`batch` — ~250 行

### 0.3 API 层兼容性

| 维度 | frontend-vue | monitor_web |
|------|-------------|-------------|
| baseURL | `http://127.0.0.1:5000` | `http://127.0.0.1:5000` |
| GET 传 Token | `?api_token=xxx` | `?api_token=xxx` ✅ |
| POST 传 Token | `Authorization: Bearer xxx` | `Authorization: Bearer xxx` ✅ |
| 响应格式 | JSON | JSON |
| 401 处理 | ✅ 已实现 | ✅ 已实现 |

**结论**：API 层完全兼容，不需要修改。但 Settings.vue 中有两个 API 端点路径不一致：
- `/api/proxy/config` (GET) — 存在
- `/api/config` (POST) — 需确认后端是否支持

### 0.4 设计风格

monitor_web 的 CSS variables.css 已采用 **DESIGN.md 的 Claude 暖色系**（Parchment #f5f4ed, Terracotta #c96442, Warm Sand #e8e6dc）。前端和后端在设计上已经对齐，不需要转换。

---

## 1. 迁移路线图（4 阶段）

```
阶段 0   →  阶段 1   →   阶段 2   →   阶段 3
预备      框架搭建     逐模块迁移    收尾集成
(1h)     (4h)       (~20h)      (2h)
```

### 阶段 0：预备工作（~1h）

#### 0.1 验证 API 端点兼容性
- [ ] 检查 `server/__main__.py` 中 `/api/config` POST 是否存在
- [ ] 检查所有 monitor_web 调用的 API 端点在 Flask 后端是否存在
- [ ] 补充 `request.ts` 中缺少的 API 方法（accounts, api-keys, proxy-pools 等）

#### 0.2 补充 i18n key
**方案**：以 monitor_web 的 `zh.json` / `en.json` 为蓝本，补充到 frontend-vue 的 locales 中。

按优先级分批补充：
- 第一批：`common`, `page.*`（页面标题/描述/按钮）— ~150 行
- 第二批：`account`, `batchDownload`（核心页面）— ~230 行
- 第三批：`config`, `settings`（配置中心）— ~200 行
- 第四批：其余所有

#### 0.3 确认模态框方案
- 采用 Naive UI 的 `NModal` + `NMessage` 作为统一模态/反馈组件
- 不自封装模态框，复用 Naive UI 组件

---

### 阶段 1：框架迁移（~4h）

#### 1.1 侧边栏组件（`Sider.vue` 重构）

**当前状态**：只有 2 个菜单项（index/setting）+ 底部主题/语言/关于。

**目标状态**：
- 一级菜单：Dashboard、账户管理、批量下载、API Keys、代理池、动态代理、切片历史、资源嗅探
- 设置组：配置中心（含 7 个子页面）
- 底部：主题切换、语言切换、关于

**文件变更**：
| 文件 | 操作 | 说明 |
|------|------|------|
| `components/layout/Sider.vue` | 重构 | 完整侧边栏（含折叠子菜单） |
| `router/index.ts` | 扩展 | 添加 9 个主路由 + 7 个设置子路由 |
| `locales/zh.json` | 补充 | nav.* namespace |
| `locales/en.json` | 补充 | nav.* namespace |

#### 1.2 顶部栏组件（新建）

**功能**：
- 左侧：页面标题（随路由动态切换）
- 右侧：语言切换按钮（CN / EN）

**文件变更**：
| 文件 | 操作 | 说明 |
|------|------|------|
| `components/layout/Header.vue` | 新建 | 顶部栏 |

#### 1.3 主布局容器（`App.vue` 调整）

**当前**：`<div class="w-full h-full p-4"><RouterView /></div>`

**目标**：侧边栏 + 顶部栏 + 主内容区的完整布局壳

**文件变更**：
| 文件 | 操作 | 说明 |
|------|------|------|
| `App.vue` | 重构 | 侧边栏 + 顶部栏 + 主内容区 |
| `components/layout/Index.vue` | 调整 | 作为页面内容区容器 |

#### 1.4 退出条件验证

阶段 1 完成后，需要验证：
- [ ] 侧边栏 9 个导航项全部可点击跳转
- [ ] 设置子菜单可折叠/展开
- [ ] 顶部栏标题随路由切换
- [ ] 语言切换生效
- [ ] 资源嗅探页面在壳下无错位
- [ ] 无双滚动条

---

### 阶段 2：功能模块逐页迁移（~20h）

按复杂度排序，先易后难：

#### 模块 1：资源嗅探（已有）— 0.5h
- 功能已验证通过
- 只做样式对齐：表格疏密、筛选标签样式、操作列对齐
- 对照 `monitor_web/index.html` 中 `#page-resources` 的表格结构

#### 模块 2：API Keys — 1.5h
- 页面：列表展示 + 新增/编辑/删除
- 复杂度低（只有列表 + 弹窗表单），适合作为第一个迁移练手
- 对照 `monitor_web/index.html` 中 `#page-api-keys`

#### 模块 3：固定代理池 — 2h
- 页面：节点列表 + 添加节点 + 演示视频弹窗
- 对照 `monitor_web/index.html` 中 `#page-proxy-pools`

#### 模块 4：Dashboard（数据概览）— 3h
- 页面：统计卡片（监控账户数/扫描次数/新增视频/Quota/最后扫描）
- 扫描事件日志（SSE 实时更新）
- 对照 `monitor_web/index.html` 中 `#page-dashboard`
- **注意**：eventStore 已有 SSE 基础设施，需扩展扫描事件处理

#### 模块 5：账户管理 — 4h
- 页面：账户表格 + 添加/编辑弹窗 + 调度器控制 + 重载任务
- 这是最复杂的模块，有大量表单字段
- 对照 `monitor_web/index.html` 中 `#page-channels`

#### 模块 6：批量下载 — 4h
- 页面：文件上传区（Excel/CSV/TXT）+ 配置面板 + 最近任务列表 + 下载进度
- 涉及文件上传（FormData）和 SSE 进度推送
- 对照 `monitor_web/index.html` 中 `#page-downloads`

#### 模块 7：动态代理提供方 — 3h
- 页面：调度器状态卡 + 日志面板 + 提供方表格 + 详情抽屉
- 对照 `monitor_web/index.html` 中 `#page-dynamic-providers`

#### 模块 8：切片历史 — 1.5h
- 页面：筛选工具栏 + 任务表格 + 分页
- 对照 `monitor_web/index.html` 中 `#page-clip-history`

#### 模块 9：配置中心（7 个子页）— 6h
- 通知与 Webhook
- API 与扫描
- 下载设置
- AI 切片
- 系统动态代理
- 代理嗅探
- 全局配置弹窗
- 对照 `monitor_web/templates/pages/settings-*.html`

---

### 阶段 3：收尾集成（~2h）

- [ ] i18n 完整性检查（对比 monitor_web 的 1245 行 vs frontend-vue 目标行数）
- [ ] 所有页面路由验证
- [ ] SSE 事件系统完整性检查
- [ ] 模态框统一性检查

---

## 2. 关键设计决策

### 2.1 样式策略

**直接复用 monitor_web 已定义的 CSS 变量和样式**：
- `variables.css` 的 CSS 变量（已采用 DESIGN.md 的 Claude 暖色系）
- `layout.css` 的布局规则（.app / .header / .main / .card）
- `table.css` / `modal.css` / `form.css` 等

**实现方式**：将 monitor_web 的 CSS 变量文件复制到 frontend-vue 的 `src/styles/` 下，按需引入。不从零重写样式。

### 2.2 API 层策略

**复用现有 `request.ts`**，补充缺失的 API 方法：
```typescript
// 补充 API 方法到 app.ts 或新建 api/monitor.ts
export const getAccounts = () => request({ url: '/api/accounts', method: 'get' })
export const addAccount = (data) => request({ url: '/api/accounts', method: 'post', data })
export const getApiKeys = () => request({ url: '/api/api-keys', method: 'get' })
// ...以此类推
```

### 2.3 组件封装

**按功能封装可复用组件**：
```
src/components/
├── layout/          # 已有：Index.vue, Sider.vue, Header.vue（新建）
├── common/          # 新建：PageHeader.vue, StatCard.vue, DataTable.vue
├── modals/          # 新建：AccountModal.vue, ApiKeyModal.vue, ProxyModal.vue
├── batch/           # 新建：FileUpload.vue, BatchProgress.vue
└── ...
```

### 2.4 资源嗅探特殊处理

按 Cursor 方案 §2，执行：
- **功能以 frontend-vue 的 ResourceIndex.vue 为准**，不迁移 monitor_web 的资源嗅探逻辑
- **样式可借鉴** monitor_web 的表格/筛选/操作列外观层级，在 Vue 内用 Naive UI 组件复刻

---

## 3. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| monitor_web 的页面逻辑嵌套在 HTML 里，迁移时需要从 JS 提取业务逻辑 | 中 | 每个模块独立迁移，逐个验证 |
| i18n 差距大（1043 行），补全工作量大 | 低 | 分批补充，每模块迁移时补对应 namespace |
| SSE 事件类型需要和后端确认 | 中 | 阶段 1 结束时验证 Dashboard 的 SSE 连接 |
| 17 个模态框迁移工作量 | 中 | 统一用 Naive UI Modal，减少重复封装 |

---

## 4. 文件变更清单（总览）

### 新建文件
```
src/
├── components/layout/Header.vue
├── components/layout/AppLayout.vue
├── components/common/PageHeader.vue
├── components/common/StatCard.vue
├── components/modals/AccountModal.vue
├── components/modals/ApiKeyModal.vue
├── components/modals/ProxyModal.vue
├── components/modals/DynamicProviderModal.vue
├── views/Dashboard.vue
├── views/Accounts.vue
├── views/BatchDownload.vue
├── views/ApiKeys.vue
├── views/ProxyPools.vue
├── views/DynamicProviders.vue
├── views/ClipHistory.vue
├── views/SettingsHub.vue
├── views/settings/NotifySettings.vue
├── views/settings/ApiSettings.vue
├── views/settings/DownloadSettings.vue
├── views/settings/AiSettings.vue
├── views/settings/DynamicProxySettings.vue
├── views/settings/ProxySnifferSettings.vue
├── styles/variables.css
├── styles/layout.css
├── styles/common.css
└── styles/modal.css
```

### 修改文件
```
src/
├── App.vue                    # 重构布局
├── router/index.ts            # 扩展路由
├── locales/zh.json            # 补充 1000+ 行
├── locales/en.json            # 补充 1000+ 行
├── components/layout/Sider.vue    # 重构侧边栏
├── api/request.ts             # 补充缺失 API
├── views/ResourceIndex.vue    # 样式对齐
├── views/Settings.vue         # 扩展为 SettingsHub
└── views/setting.vue          # 替换为 SettingsHub
```

---

*本方案基于 `docs/analysis_results.md` 分析和实际代码盘点，量化了 i18n 差距（1043 行）、明确了 API 兼容性（✅ 完全兼容）、指定了具体文件和变更范围，可直接作为任务拆解和进度跟踪的依据。*
# 资源嗅探功能 Vue 迁移设计方案

**日期**: 2026-04-22
**目标**: 将 res-downloader 前端的资源嗅探功能完整迁移到 ytdlp-batch-downloader 项目

---

## 一、背景与目标

### 现状问题

1. **下载失败** — Go 侧 `SaveDirectory` 为空，下载静默退出
2. **预览失败** — Flask 的加密预览实现架构性错误（全量下载+部分解密）
3. **前端不可用** — 当前项目的 `decrypt.js` / `decrypt.wasm` 名存实亡
4. **配置不统一** — 下载目录分散在多处，没有统一管理

### 迁移目标

1. 将 res-downloader 前端的**完整资源嗅探功能**迁移到当前项目
2. 下载目录**持久化到 Python config.json**，Flask 同步给 Go
3. 视频预览（普通/FLV/加密）**复用官方前端实现**，不依赖 Python 解密逻辑
4. 最终形态：**Vue 3 SPA + Naive UI + Flask API**

---

## 二、架构设计

### 最终架构

```
┌─────────────────────────────────────────────────────┐
│  monitor_ui.py (tkinter + pywebview)                │
│    └── WebView (Edge Chromium)                     │
│         └── Vue 3 SPA (Naive UI)                  │
│              ├── 资源嗅探页面 (views/Index.vue)     │
│              ├── 预览播放器 (components/Preview.vue)│
│              └── 设置页面 (views/Settings.vue)      │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  Flask HTTP Server (server/__main__.py)           │
│    ├── REST API: /api/proxy/*, /api/res/*         │
│    ├── SSE: /api/res-events  (转发 Go WS 事件)    │
│    └── Static Files: /  (Vue SPA build output)    │
└─────────────────────────────────────────────────────┘
          │                              │
          ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  Go Proxy (res-      │    │  Python config.json      │
│  downloader.exe)       │    │  (download_output_path)   │
│  /api/download        │    └──────────────────────────┘
│  /api/preview        │
│  /ws (WebSocket)     │
└──────────────────────┘
```

### 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 前端框架 | Vue 3 + Vite + Naive UI | 与 res-downloader 保持一致，便于代码迁移 |
| 事件通道 | SSE (Flask → Browser) | 现有架构已实现，无需改动 Go |
| 下载目录 | Python config.json | 用户偏好，持久化到 Python 侧 |
| 加密预览 | 浏览器端 XOR 解密 | 复用 res-downloader 官方实现 |
| 路由模式 | Hash (#/index, #/settings) | WebView 兼容性 |

---

## 三、数据流设计

### 3.1 下载目录配置流

```
用户设置下载目录
    ↓
Flask /api/proxy/config (body: {SaveDirectory: "..."})
    ↓
Go /api/set-config
    ↓
Go setConfig() → 写入 Go config.json (持久化)
    ↓
下载时 Go 从 globalConfig.SaveDirectory 读取 → 有效路径
```

### 3.2 资源嗅探事件流

```
Go Proxy 捕获媒体
    ↓
Go EmitEvent("newResources", mediaInfo) → /ws WebSocket 广播
    ↓
Python WS Client 接收 → _dispatch_ws_message
    ↓
SSE 事件队列 → /api/res-events
    ↓
Vue SSE EventSource → eventStore.dispatch
    ↓
Pinia store 更新 → 响应式渲染列表
```

### 3.3 视频预览流

| 类型 | 预览方式 |
|------|---------|
| 普通视频 | `video.js` → `GET /api/res/preview?url=` |
| FLV 直播 | `flv.js` → `GET /api/res/preview?url=` |
| 微信加密 | 浏览器分块 XOR 解密 → `MediaSource` 流式播放 |

### 3.4 下载流

```
用户点击下载
    ↓
Vue api.download({...mediaInfo, decodeStr})
    ↓
Flask /api/res/download → Go /api/download
    ↓
Go download() 异步执行 → EmitEvent("downloadProgress", ...)
    ↓
SSE 推送进度 → Vue 更新行状态
```

---

## 四、文件迁移清单

### 4.1 需要迁移的 res-downloader 文件

#### Vue 组件 (8个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `views/index.vue` | `frontend-vue/src/views/ResourceIndex.vue` | 资源嗅探主页面 |
| `views/setting.vue` | `frontend-vue/src/views/Settings.vue` | 设置页面 |
| `components/Preview.vue` | `frontend-vue/src/components/Preview.vue` | 视频预览播放器 |
| `components/Action.vue` | `frontend-vue/src/components/ResourceAction.vue` | 操作按钮列 |
| `components/ActionDesc.vue` | `frontend-vue/src/components/ActionHeader.vue` | 操作列头 |
| `components/ShowOrEdit.vue` | `frontend-vue/src/components/InlineEdit.vue` | 描述可编辑单元格 |
| `components/ImportJson.vue` | `frontend-vue/src/components/ImportJson.vue` | JSON 批量导入 |
| `components/NaiveProvider.vue` | `frontend-vue/src/components/NaiveProvider.vue` | Naive UI 全局 provider |

#### App 根文件 (5个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `App.vue` | `frontend-vue/src/App.vue` | 根组件（简化版） |
| `main.ts` | `frontend-vue/src/main.ts` | 入口 |
| `router/index.ts` | `frontend-vue/src/router/index.ts` | 路由 |
| `stores/index.ts` | `frontend-vue/src/stores/resource.ts` | Pinia 状态（重写） |
| `stores/event.ts` | `frontend-vue/src/stores/event.ts` | 事件分发（重写） |

#### API 与类型 (4个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `api/request.ts` | `frontend-vue/src/api/request.ts` | axios 实例（改 baseURL） |
| `api/app.ts` | `frontend-vue/src/api/resource.ts` | 资源嗅探 API 封装 |
| `types/app.d.ts` | `frontend-vue/src/types/resource.ts` | TypeScript 类型定义 |
| `types/global.d.ts` | `frontend-vue/src/types/global.d.ts` | 全局类型扩展 |

#### 样式与资源 (3个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `assets/css/base.css` | `frontend-vue/src/assets/css/base.css` | 基础样式 |
| `assets/css/main.css` | `frontend-vue/src/assets/css/main.css` | 主样式 |
| `assets/js/decrypt.js` | `frontend-vue/src/assets/js/decrypt.js` | XOR 解密算法 |

#### i18n (2个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `locales/zh.json` | `frontend-vue/src/locales/zh.json` | 中文翻译 |
| `locales/en.json` | `frontend-vue/src/locales/en.json` | 英文翻译 |

### 4.2 需要重写的文件（当前项目已有）

| 目标文件 | 改动说明 |
|---------|---------|
| `server/__main__.py` | Flask 静态文件 serve + `/` → Vue SPA |
| `monitor_web/js/api.js` | 替换为 Vue axios 封装 |
| `monitor_web/js/modules/resources.js` | 废弃，被 Vue 组件替代 |
| `monitor_web/js/isaac.js` | 保留，`decrypt.js` 替代其功能 |
| `monitor_web/static/decrypt.js` | 替换为 res-downloader 版本 |

### 4.3 新增文件

| 文件路径 | 说明 |
|---------|------|
| `frontend-vue/vite.config.ts` | Vite 构建配置 |
| `frontend-vue/tailwind.config.js` | Tailwind 配置 |
| `frontend-vue/postcss.config.js` | PostCSS 配置 |
| `frontend-vue/tsconfig.json` | TypeScript 配置 |
| `frontend-vue/package.json` | 依赖声明 |
| `frontend-vue/index.html` | HTML 入口 |
| `frontend-vue/.env` | 环境变量 |

---

## 五、API 适配层设计

### 5.1 API 路由对照

| res-downloader 前端调用 | Flask 路由 | 说明 |
|----------------------|----------|------|
| `POST /api/get-config` | `GET /api/proxy/config` | 获取 Go 配置 |
| `POST /api/set-config` | `POST /api/proxy/config` | 设置 Go 配置 |
| `POST /api/set-type` | `POST /api/res/set-type` | 设置过滤类型 |
| `POST /api/clear` | `POST /api/res/clear` | 清空资源 |
| `POST /api/delete` | `POST /api/res/delete` | 删除资源 |
| `POST /api/download` | `POST /api/res/download` | 下载资源 |
| `POST /api/cancel` | `POST /api/res/cancel` | 取消下载 |
| `POST /api/wx-file-decode` | `POST /api/res/decode` | 微信文件解密 |
| `POST /api/batch-export` | `POST /api/res/export` | 批量导出 |
| `POST /api/open-folder` | `POST /api/res/open-folder` | 打开目录 |
| `POST /api/is-proxy` | `GET /api/proxy/status` | 代理状态 |
| `POST /api/app-info` | ❌ 不迁移 | Wails 专属，获取应用信息 |
| `POST /api/install` | ❌ 不迁移 | Wails 专属，安装证书走现有页面 |
| `GET /api/preview` | `GET /api/res/preview` | 视频预览代理 |
| `GET /api/preview/encrypted` | `GET /api/res/preview/encrypted` | 加密视频预览（浏览器端解密） |
| `GET /api/res-events` | `GET /api/res-events` | SSE 事件流 |
| `/ws` | WS → SSE | WebSocket 事件（Go → Python WS → Flask SSE → Browser） |

**注意**: res-downloader 前端所有 API 均为 `POST` 方式（Go 侧已支持），Flask 侧对应路由保持一致。

### 5.2 Wails Runtime 替换（重写）

**注意**: Wails `EventsOn` 是事件驱动的异步订阅模式，Flask SSE 是轮询式的 Server-Sent Events，两者架构不同。`event.ts` 需要**完全重写**而非简单映射。

| Wails API | 替换方案 | 类型 |
|----------|---------|------|
| `window.runtime.EventsOn()` | `EventSource` + `eventStore` | **重写** |
| `window.runtime.EventsEmit()` | 无需替换（Go → Python 已实现） | N/A |
| `window.runtime.BrowserOpenURL()` | `window.open()` | 直接替换 |
| `window.runtime.ClipboardSetText()` | `navigator.clipboard.writeText()` | 直接替换 |
| `window.runtime.OpenDirectoryDialog()` | 不迁移 | N/A |
| `window.runtime.Window*()` | 不迁移 | N/A |
| `bind.Config()` / `bind.AppInfo()` | Flask API 调用 | 直接替换 |

**eventStore 重写核心逻辑**:
```typescript
// 浏览器端: EventSource 连接 Flask SSE
const es = new EventSource('/api/res-events')
es.onmessage = (e) => {
  const msg = JSON.parse(e.data)  // {event: "newResources", data: {...}}
  handles.value[msg.event]?.(msg.data)
}
es.onerror = () => { /* 重连逻辑 */ }
```

---

## 六、关键组件详细设计

### 6.1 ResourceIndex.vue（主页面）

**功能**:
- NDataTable 展示资源列表（复选框/Domain/类型/预览/状态/描述/大小/操作）
- 顶部工具栏（类型过滤/搜索/批量下载/导入/清空）
- 右键菜单/操作列
- 实时接收 SSE 事件更新

**状态**:
```typescript
interface ResourceState {
  data: MediaInfo[]           // 资源列表
  checkedKeys: string[]       // 选中行的 UrlSign
  typeFilter: string[]        // 类型过滤 ["all"]
  searchValue: string          // 描述搜索
  activeDownloads: number      // 活跃下载数
  downloadQueue: MediaInfo[]    // 下载队列
}
```

### 6.2 Preview.vue（预览播放器）

**三种模式**:
1. **普通视频**: `video.js` → `/api/res/preview?url=`
2. **FLV 直播**: `flv.js` → `/api/res/preview?url=`
3. **微信加密**: `MediaSource` + 分块下载 + XOR 解密

**加密预览核心流程**:
```
playVideoWithoutTotalLength()
  → 初始化 MediaSource + SourceBuffer
  → buildUrlWithParams() (提取 encfilekey + token)
  → getDecryptionArray(decodeKey) 生成 keystream
  → downloadChunk() 分块下载 (Range: bytes=0-5242879)
  → chunk[i] ^= decodeArr[startByte + i]  XOR 解密
  → sourceBuffer.appendBuffer(decryptedChunk)
  → 循环直到 byteLength === 0 → mediaSource.endOfStream()
```

### 6.3 ResourceAction.vue（操作列）

**按钮**:
- 下载（绿色，live/m3u8 类型禁用）
- 删除（红色）
- 更多操作下拉：
  - 取消下载
  - 复制链接
  - 浏览器打开
  - 微信解密（DecodeKey 存在时）
  - 复制 JSON

### 6.4 Settings.vue（设置页面）

**配置项**:
- `SaveDirectory`: 下载目录（必填，Flask config.json）
- `DownNumber`: 并发下载数
- `TaskNumber`: 每个任务的连接数
- `FilenameLen`: 文件名长度限制
- `FilenameTime`: 是否追加时间戳
- `InsertTail`: 新资源追加到末尾
- `MimeMap`: MIME 类型映射

---

## 七、Phase 0 — 源文件获取（前置步骤）

迁移源文件位于：`D:\WORKSPACE\video-download-space\res-downloader\frontend\src\`

**在开始任何代码迁移前，需确认以下文件已就绪**：

```bash
# 验证源文件目录
ls res-downloader/frontend/src/
# 应包含: views/, components/, api/, stores/, types/, assets/, locales/, router/

# 验证关键文件存在
ls res-downloader/frontend/src/views/index.vue      # 主页面
ls res-downloader/frontend/src/components/Preview.vue  # 预览播放器
ls res-downloader/frontend/src/stores/event.ts       # 事件分发
ls res-downloader/frontend/src/assets/js/decrypt.js    # XOR 解密
```

**迁移策略**：直接引用源文件路径进行迁移，不做物理移动，后续 git 保持独立仓库的 clean 状态。

---

## 八、实施阶段

### Phase 1: 基础设施（1-2天）

1. 初始化 `frontend-vue/` 项目结构
2. 配置 Vite + Vue 3 + Naive UI + Tailwind + TypeScript
3. 配置 axios（baseURL → Flask API）
4. 实现 Pinia store 骨架
5. 配置 vue-i18n
6. Flask 改造：serve Vue build 输出，API 路由保持不变

### Phase 2: 核心功能迁移（2-3天）

1. 迁移 `decrypt.js`
2. 实现 `event.ts`（SSE 事件接收 + 分发）
3. 实现 `resource.ts`（API 封装）
4. 迁移 `Preview.vue`（三种预览模式）
5. 迁移 `ResourceIndex.vue`（资源列表 + 过滤）
6. 迁移 `ResourceAction.vue`（操作按钮）
7. 实现下载进度追踪

### Phase 3: 功能完善（1-2天）

1. 迁移 `ImportJson.vue`（批量导入）
2. 迁移 `InlineEdit.vue`（描述编辑）
3. 迁移 `ActionHeader.vue`
4. 迁移 `Settings.vue`（SaveDirectory 持久化到 Python config.json）
5. 实现下载目录配置同步（Flask → Go）

### Phase 4: 收尾（0.5天）

1. 清理旧的 `monitor_web/js/modules/resources.js`
2. 清理旧的 Flask Jinja 模板（如果全部迁移完成）
3. 确认所有 API 路由正确
4. 回归测试

---

## 九、风险与注意事项

| 风险 | 影响 | 应对 |
|------|------|------|
| Go `/api/set-config` 的 SaveDirectory 必须和 Python config.json 同步 | 用户在 Python 侧改了路径，Go 侧不知道 | Flask 在保存 Python config 时同步推给 Go |
| `decrypt.js` 的 ISAAC 算法需与 Go 侧一致 | 解密失败 | 直接复用 res-downloader 官方文件，已有测试用例 |
| SSE 断线重连 | 事件丢失 | Vue EventSource 组件内处理重连逻辑 |
| WebView 对 Vue DevTools 支持有限 | 调试困难 | 开发阶段用 Chrome，WebView 验证最终效果 |
| Naive UI 组件版本兼容性 | 编译错误 | 锁定版本号（naive-ui 2.38.2） |

---

## 十、验收标准

1. 资源嗅探页面加载后，能实时显示 Go 捕获的媒体资源
2. 点击视频行可以预览（非加密走 video.js，微信加密走分块 XOR 解密）
3. 点击下载，文件正确保存到配置的目录
4. 批量下载正常工作（并发数受 DownNumber 控制）
5. 复制链接、浏览器打开功能正常
6. 刷新页面后资源列表从 localStorage 恢复
7. SSE 断线后自动重连
8. 下载目录配置在 Flask config.json 中持久化

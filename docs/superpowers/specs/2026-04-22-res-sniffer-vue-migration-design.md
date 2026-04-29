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

### 0.1 Tailwind CSS 使用说明

res-downloader 源项目不使用 Tailwind，迁移时引入 Tailwind 的目的是**未来 UI 增强**（设置页面表单样式等）。

**当前迁移阶段**（Phase 1-3）：组件使用 `assets/css/base.css` 和 `assets/css/main.css` 中的原生 CSS，Tailwind 可不配置或仅配置基础变量（颜色、字体）。
**未来增强阶段**（Phase 4+）：逐步将原生 CSS 迁移为 Tailwind 原子类。

```
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

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
| `stores/index.ts` | `frontend-vue/src/stores/resource.ts` | Pinia 状态管理（含 appInfo/globalConfig/isProxy/baseUrl，拆分出 event.ts 后重写） |
| `stores/event.ts` | `frontend-vue/src/stores/event.ts` | 事件分发（重写） |

#### API 与类型 (4个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `api/request.ts` | `frontend-vue/src/api/request.ts` | axios 实例（改 baseURL） |
| `api/app.ts` | `frontend-vue/src/api/resource.ts` | 资源嗅探 API 封装 |
| `types/app.d.ts` | `frontend-vue/src/types/resource.ts` | TypeScript 类型定义 |
| `types/global.d.ts` | `frontend-vue/src/types/global.d.ts` | 全局类型扩展 |

#### 样式与资源 (5个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `assets/css/base.css` | `frontend-vue/src/assets/css/base.css` | 基础样式（Naive UI + Tailwind 变量定义） |
| `assets/css/main.css` | `frontend-vue/src/assets/css/main.css` | 主样式（Tailwind directives + #app 样式） |
| `assets/js/decrypt.js` | `frontend-vue/src/assets/js/decrypt.js` | XOR 解密算法 |
| `i18n.ts` | `frontend-vue/src/i18n.ts` | i18n 配置 |
| `func.ts` | `frontend-vue/src/func.ts` | 工具函数 |

#### i18n (4个)

| 源文件 | 目标文件 | 说明 |
|--------|---------|------|
| `locales/zh.json` | `frontend-vue/src/locales/zh.json` | 中文翻译 |
| `locales/en.json` | `frontend-vue/src/locales/en.json` | 英文翻译 |
| `i18n.ts` | `frontend-vue/src/i18n.ts` | vue-i18n 配置（重写：挂载到 App.vue，注入 locale/资源） |
| `func.ts` | `frontend-vue/src/func.ts` | 工具函数（formatSize/isValidHost/isValidPort/compareVersions，直接迁移） |

### 4.2 需要重写的文件（当前项目已有）

| 目标文件 | 改动说明 |
|---------|---------|
| `server/__main__.py` | Flask 静态文件 serve + `/` → Vue SPA |
| `monitor_web/js/api.js` | 保留（备份），Vue API 层独立实现 |
| `monitor_web/js/modules/resources.js` | 保留（备份），新功能在 Vue 实现 |
| `monitor_web/js/isaac.js` | 保留，`decrypt.js` 替代其功能 |
| `monitor_web/static/decrypt.js` | 保留（备份），`frontend-vue/src/assets/js/decrypt.js` 为新实现 |

### 4.3 新增文件

| 文件路径 | 说明 |
|---------|------|
| `frontend-vue/vite.config.ts` | Vite 构建配置 |
| `frontend-vue/tailwind.config.js` | Tailwind 配置 |
| `frontend-vue/postcss.config.js` | PostCSS 配置 |
| `frontend-vue/tsconfig.json` | TypeScript 配置 |
| `frontend-vue/package.json` | 依赖锁定版本（naive-ui 2.38.2, vue ^3.4.0 等） |
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
// 浏览器端: EventSource 连接 Flask SSE（必须传 api_token）
const token = sessionStorage.getItem('monitor_api_token') || window.__MONITOR_API_TOKEN__ || '';
const es = new EventSource('/api/res-events?api_token=' + encodeURIComponent(token));
es.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  // Go send() 发 {"type": "newResources", "data": {...}}
  // Python _dispatch_ws_message 透传后 SSE: data: {"type": "...", "data": {...}}
  // 注意: msg.event 是 undefined，需用 msg.type 获取事件类型
  const eventType = msg.event || msg.type;
  const eventData = msg.data?.data || msg.data; // 双层 unwrap
  if (!eventType) return;
  if (handles.value[eventType]) {
    try {
      handles.value[eventType](eventData);
    } catch (err) {
      console.error('[eventStore] Handler error for', eventType, err);
    }
  } else {
    console.warn('[eventStore] No handler for event:', eventType);
  }
};
// EventSource 不支持自定义 Header，token 必须通过 URL 参数传递
// Flask _require_auth() 会读取 ?api_token= 参数
es.onerror = () => {
  es.close(); // 必须先关闭旧实例避免处理器堆积
  const delay = Math.min(30000, 1000 * Math.pow(2, reconnectAttempts));
  reconnectAttempts++;
  setTimeout(() => new es('/api/res-events?...'), delay);
};
```

// 补充：去重 + 错误处理 + 清理
const registered = new Set<symbol>();

const addHandle = (handle: { type: string; event: Function }) => {
  if (registered.has(Symbol.for(handle.type))) {
    console.warn(`[eventStore] Overwriting existing handler for: ${handle.type}`);
  }
  registered.add(Symbol.for(handle.type));
  handles.value[handle.type] = handle.event;
};

const removeHandle = (type: string) => {
  handles.value[type] = undefined;
  registered.delete(Symbol.for(type));
};

组件卸载时需调用 removeHandle() 防止内存泄漏：
onBeforeUnmount(() => { removeHandle('newResources'); removeHandle('downloadProgress'); });

### 5.2.1 SSE 认证机制

Flask `_require_auth()` 在 SSE 端点要求认证。EventSource **不支持自定义 HTTP Header**，token 必须通过 URL 参数传递。

Flask 认证读取顺序：
1. `Authorization: Bearer <token>` Header
2. `?api_token=<token>` URL 参数（EventSource fallback）

前端获取 token 优先级：
```typescript
const token = sessionStorage.getItem('monitor_api_token')
  || (typeof window !== 'undefined' && window.__MONITOR_API_TOKEN__)
  || '';
```

Flask 侧无需额外修改，`_require_auth()` 已支持 `?api_token=` fallback。

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

#### 6.2.1 加密预览安全问题

**风险**：`GET /api/res/preview?url=...&decodeKey=...` 中的 decodeKey 会出现在：
- 浏览器历史记录
- 代理日志（mitmproxy）
- Referer header

**缓解**（Phase 3 增强，非当前阶段必需）：
- 方案A：改用 POST body 传递 decodeKey，Flask 解密后透传加密流
- 方案B：Flask 层清洗 Referer header
- 当前阶段：保持 GET URL 方式（localhost 单用户威胁模型内可接受），后续优化

#### 6.2.2 MediaSource 内存管理

加密预览播放器必须显式清理资源，否则每次预览泄漏一个 MediaSource 实例。

Vue composable 封装：
```typescript
// src/composables/useEncryptedPreview.ts
import { ref, onBeforeUnmount } from 'vue';

export function useEncryptedPreview() {
  const mediaSource = ref<MediaSource | null>(null);
  const playerRef = ref<HTMLVideoElement | null>(null);

  const dispose = () => {
    if (mediaSource.value) {
      mediaSource.value = null;
    }
    if (playerRef.value) {
      playerRef.value.src = '';
      playerRef.value.load();
    }
    URL.revokeObjectURL(playerRef.value?.src || '');
  };

  onBeforeUnmount(dispose);

  return { mediaSource, playerRef, dispose };
}
```

组件中使用：
```vue
<script setup>
const { mediaSource, playerRef, dispose } = useEncryptedPreview();
</script>
<video ref="playerRef" />
```

**禁止**：导航时不调用 cleanup。仅 `dispose()` 中清理，不依赖垃圾回收。

#### 6.2.3 加密预览性能优化

每轮 chunk 下载/解密/播放周期约 30MB 峰值（axios buffer + keystream + 解密 buffer + SourceBuffer）。

当前阶段：顺序处理即可（简单可靠）。
后续优化（Phase 4+）：
- 双缓冲：后台下载 N+1 chunk，前台解密播放 N chunk
- AbortController：取消进行中的请求
- chunk 大小自适应：根据网速动态调整（慢网用大 chunk，快网用小 chunk）

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

## 七、Phase 0 — 源文件获取与目录初始化（前置步骤）

迁移源文件位于：`D:\WORKSPACE\video-download-space\res-downloader\frontend\src\`

**重要**：当前 `monitor_web/` 目录**作为备份保留**，不删除。新功能在 `frontend-vue/` 目录实现。Flask serve 路径从 `monitor_web/` 切换到 `frontend-vue/dist/` 时，旧代码仍有备份可查。

### Step 0.1: 创建 Vue 项目结构

```bash
# 在项目根目录创建 frontend-vue/
mkdir frontend-vue
cd frontend-vue

# 初始化 package.json（含锁定版本）
npm init -y

# 安装依赖
npm install vue@^3.4.0 naive-ui@2.38.2 pinia@^2.1.0 vue-router@^4.3.0 vue-i18n@^9.10.0 axios@^1.6.0 video.js@^8.10.0 flv.js@^0.8.0

# 开发依赖
npm install -D vite@^5.2.0 @vitejs/plugin-vue@^5.0.0 tailwindcss@^3.4.0 postcss autoprefixer typescript vue-tsc
```

### Step 0.2: 复制源文件

```bash
# 复制 Vue 源文件（从 res-downloader 到 frontend-vue/src/）
cp -r ../res-downloader/frontend/src/views    src/
cp -r ../res-downloader/frontend/src/components src/
cp -r ../res-downloader/frontend/src/api     src/
cp -r ../res-downloader/frontend/src/stores  src/
cp -r ../res-downloader/frontend/src/types  src/
cp -r ../res-downloader/frontend/src/assets src/
cp -r ../res-downloader/frontend/src/router  src/
cp -r ../res-downloader/frontend/src/App.vue src/
cp -r ../res-downloader/frontend/src/main.ts src/
cp -r ../res-downloader/frontend/src/i18n.ts src/
cp -r ../res-downloader/frontend/src/func.ts src/
```

### Step 0.3: 初始化配置文件

```bash
# 创建构建配置
cp ../res-downloader/frontend/vite.config.ts src/../vite.config.ts
cp ../res-downloader/frontend/tailwind.config.js src/../tailwind.config.js
cp ../res-downloader/frontend/postcss.config.js src/../postcss.config.js
cp ../res-downloader/frontend/tsconfig.json src/../tsconfig.json
cp ../res-downloader/frontend/index.html src/../index.html
```

### Step 0.4: 验证源文件

```bash
# 验证关键文件存在
ls src/views/index.vue      # 主页面
ls src/components/Preview.vue  # 预览播放器
ls src/stores/event.ts       # 事件分发
ls src/assets/js/decrypt.js  # XOR 解密
ls src/assets/css/base.css    # 基础样式
ls src/assets/css/main.css    # 主样式
ls src/i18n.ts              # i18n 配置
```

**迁移策略**：从 res-downloader 源码目录直接复制，保持 git 独立仓库干净。后续同步更新时重新复制即可。

### 0.5 配置同步约定

下载目录持久化在 Python config.json，Flask 作为中间层转发到 Go。

写入路径：用户设置 → Python config.json → POST /api/proxy/config → Go globalConfig → 内存生效
读取路径：Go download() → globalConfig.SaveDirectory（仅内存）
Flask 启动时：GET /api/proxy/config → 确认 Go SaveDirectory 与 Python 一致

---

## 八、实施阶段

### Phase 1: 基础设施（1-2天）

1. 初始化 `frontend-vue/` 项目结构
2. 配置 Vite + Vue 3 + Naive UI + Tailwind + TypeScript
3. 配置 axios（baseURL → Flask API）
4. 实现 Pinia store 骨架
5. 配置 vue-i18n
6. Flask 改造：serve Vue build 输出，API 路由保持不变

### Phase 1 补充步骤：

#### 1.3. Flask 改造：serve Vue SPA

Flask 静态文件 serve 改造步骤：

a) 在 `server/__main__.py` 中添加 Vue SPA 路由（加在现有静态文件路由之前）：

```python
# Vue SPA fallback（所有非 API 路由返回 index.html）
@app.route('/<path:fallback>')
def vue_spa_fallback(fallback):
    if fallback.startswith('api/'):
        return "Not Found", 404
    return send_from_directory('frontend-vue/dist', fallback)

@app.route('/')
def vue_index():
    return send_from_directory('frontend-vue/dist', 'index.html')
```

b) Vue build 输出路径：`frontend-vue/dist/` → Flask serve 目录
c) 验证：启动 Flask 后访问 / 应返回 Vue SPA 的 index.html
d) 兼容：旧的 `monitor_web/` 作为备份保留，Phase 4 清理时仅删除已被 Vue 完全替代的部分

### Phase 2: 核心功能迁移（2-3天）

1. 迁移 `decrypt.js`
注意：`frontend-vue/src/assets/js/decrypt.js` 和 `monitor_web/static/decrypt.js` 独立维护。`frontend-vue/dist/` 中的 decrypt.js 由 Vite build 输出决定，与旧文件无自动同步。
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

**重要**：`monitor_web/` 作为备份保留，不删除。只清理已被 Vue 完全替代的特定文件。

1. 对齐 API：确认 `resources.js` 中的 SSE 事件处理与 Phase 1 新增的 eventStore 逻辑一致
2. 回归测试：旧 `monitor_web/` 中不受迁移影响的路由（下载历史、账户管理、调度器等）继续正常工作
3. 确认所有 API 路由正确
4. 回归测试

---

## 九、CI/CD 补充：打包流水线修改

### PyInstaller 修改

当前 `YouTubeMonitor.spec` 只打包 `monitor/` 和 `monitor_web/`。需要新增：

1. 复制 Vue build 输出到 monitor_web/static/：
   ```bash
   # 构建 Vue 后执行
   cp -r frontend-vue/dist/* monitor_web/static/
   ```

2. 在 PyInstaller spec 中添加 Go exe 引用（如果用户配置了本地编译）：
   ```python
   # 示例：在 spec 中添加 Go exe
   a.datas += [('res-downloader.exe', 'D:/WORKSPACE/video-download-space/res-downloader/res-downloader.exe', 'DATA')]
   ```

3. 现有流程（文件系统查找 exe）保持不变作为 fallback

### 开发脚本

为方便本地开发，补充 package.json scripts：

在 `package.json` 中添加：

```json
{
  "scripts": {
    "dev": "cd frontend-vue && npm run dev",
    "build": "cd frontend-vue && npm run build",
    "dev:full": "concurrently \"npm run dev\" \"python monitor_ui.py --browser\"",
    "build:all": "npm run build && cp -r frontend-vue/dist/* monitor_web/static/"
  }
}
```

注意：`concurrently` 需安装：`npm install -D concurrently`

本地开发流程：
```bash
# 终端1：启动 Vue dev server (HMR)
npm run dev

# 终端2：启动 Flask + Python UI
python monitor_ui.py --browser
```

---

## 十、风险与注意事项

| 风险 | 影响 | 应对 |
|------|------|------|
| Go `/api/set-config` 的 SaveDirectory 必须和 Python config.json 同步 | 用户在 Python 侧改了路径，Go 侧不知道 | Flask 在保存 Python config 时同步推给 Go |
| Python/Go 双配置不一致 | 中 | Python 侧改路径后立即同步推送到 Go | Flask 在保存 Python config 时同步调用 POST /api/proxy/config 推送到 Go |
| `decrypt.js` 的 ISAAC 算法需与 Go 侧一致 | 解密失败 | 直接复用 res-downloader 官方文件，已有测试用例 |
| SSE 断线重连 | 事件丢失 | Vue EventSource 组件内处理重连逻辑 |
| WebView 对 Vue DevTools 支持有限 | 调试困难 | 开发阶段用 Chrome，WebView 验证最终效果 |
| Naive UI 组件版本兼容性 | 编译错误 | 锁定版本号（naive-ui 2.38.2） |

| SSE 端点认证不一致 | 低 | spec 未文档化但代码已实现 | 在 5.2.1 SSE 认证机制 中补充说明 Flask _require_auth() 已强制认证 |

### Phase Gate Criteria（阶段验收标准）

| Phase | 进入下一阶段前必须满足 |
|-------|----------------------|
| Phase 0 | frontend-vue/ 目录创建，npm install 成功，npm run build 成功 |
| Phase 1 | Flask 访问 / 返回 Vue index.html，/api/res-events 能连上（无 401） |
| Phase 2 | 资源列表显示 newResources 事件，视频预览能播放，加密预览能解密播放 |
| Phase 3 | 批量下载正常，Settings 保存路径生效，下载目录正确 |
| Phase 4 | 所有 acceptance criteria 通过 |

**回滚策略**：
- Phase 1 回滚：Flask 恢复 serve `monitor_web/`
- Phase 2 回滚：禁用 Vue 资源页面，启用旧 resources.js
- Phase 3 回滚：Flask config 恢复推送旧路径

---

## 十、验收标准

1. **SSE 连接**：`new EventSource('/api/res-events?api_token=xxx')` 连接后 1s 内收到 newResources 事件
2. **资源列表**：`data-value` 包含 mediaInfo 字段（UrlSign/Url/Classify/Size）
3. **视频预览**：
   - 普通：video.js player 加载成功，`play()` 返回 promise
   - 加密：MediaSource 初始化成功，SourceBuffer 追加 chunk 后触发 `encrypted` 状态
4. **下载**：`POST /api/res/download` 返回 code:1，文件写入 SaveDirectory
5. **批量下载**：DownNumber=3 时最多 3 个并发下载，其余排队
6. **刷新恢复**：localStorage 存储 mediaInfo[]，刷新后 data 恢复
7. **SSE 重连**：断开后 5s 内自动重连（指数退避）
8. **路径持久化**：修改 SaveDirectory 后重启 Flask，Go 侧 GET /api/proxy/config 返回新路径

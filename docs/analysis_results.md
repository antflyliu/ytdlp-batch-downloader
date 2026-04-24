# frontend-vue vs monitor_web 功能对比分析

## 结论：❌ 远未集成 monitor_web 的全部功能

`frontend-vue` 来自 **res-downloader** 项目（桌面端 Wails 应用），是一个**资源嗅探/代理抓包**工具的前端。而 `monitor_web` 是一个**完整的 YouTube 频道监控管理平台**的 Web 前端。两者的**业务领域完全不同**，frontend-vue 仅移植了极少部分功能。

---

## 功能对照表


| 功能模块                       | monitor_web                                    | frontend-vue                        | 状态    |
| -------------------------- | ---------------------------------------------- | ----------------------------------- | ----- |
| **数据概览 Dashboard**         | ✅ 监控账户数、扫描次数、新增视频、API Quota、最后扫描时间             | ❌ 无                                 | 🔴 缺失 |
| **账户管理 Channels**          | ✅ 添加/编辑/删除监控账户、搜索过滤、启动/停止调度器、重载任务              | ❌ 无                                 | 🔴 缺失 |
| **批量下载 Downloads**         | ✅ 上传 Excel/CSV/TXT、配置画质/字幕/代理/Cookie、进度面板、最近任务 | ❌ 无                                 | 🔴 缺失 |
| **API Keys 管理**            | ✅ 新增/编辑/删除 API Key、独立配额                        | ❌ 无                                 | 🔴 缺失 |
| **固定代理池 Proxy Pools**      | ✅ 添加/编辑/删除/启用代理节点、演示视频                         | ❌ 无                                 | 🔴 缺失 |
| **动态代理 Dynamic Providers** | ✅ 提供方 CRUD、调度器控制、健康检查、日志面板、分页搜索                | ❌ 无                                 | 🔴 缺失 |
| **切片历史 Clip History**      | ✅ 筛选/分页/详情查看切片任务                               | ❌ 无                                 | 🔴 缺失 |
| **视频详情 Video Detail**      | ✅ 全屏视频详情、搜索/分页/批量下载/重试                         | ❌ 无                                 | 🔴 缺失 |
| **资源嗅探 Resources**         | ✅ 代理捕获媒体资源、类型过滤、预览/下载/解密、批量管理                  | ⚠️ 部分实现（ResourceIndex.vue 简化版）      | 🟡 部分 |
| **配置中心 Settings**          | ✅ 7 个子页（通知/API/下载/AI切片/动态代理/代理嗅探/全局配置）         | ⚠️ 仅有基础设置（代理相关设置）                   | 🟡 部分 |
| **全局配置弹窗**                 | ✅ 完整配置管理                                       | ❌ 无                                 | 🔴 缺失 |
| **API 缓存管理**               | ✅ 缓存列表/刷新/删除                                   | ❌ 无                                 | 🔴 缺失 |
| **扫描确认弹窗**                 | ✅ 立即扫描确认                                       | ❌ 无                                 | 🔴 缺失 |
| **SSE 事件系统**               | ✅ 扫描事件日志                                       | ⚠️ 有 SSE 基础设施（eventStore），但缺少扫描相关事件 | 🟡 部分 |
| **i18n 国际化**               | ✅ 完整中英文                                        | ⚠️ 有基础设施，但翻译 key 覆盖不全               | 🟡 部分 |
| **ISAAC 解密 (WASM)**        | ✅ decrypt.wasm + isaac.js                      | ❌ 无（仅有 decrypt.js 占位）               | 🔴 缺失 |
| **侧边栏导航**                  | ✅ 9+ 页面 + 配置子菜单（可折叠）                           | ⚠️ 仅 2 项（首页 + 设置）                   | 🟡 极简 |


---

## 架构差异


| 维度        | monitor_web                                              | frontend-vue                                  |
| --------- | -------------------------------------------------------- | --------------------------------------------- |
| **技术栈**   | 原生 HTML + ES Module JS（无框架）                              | Vue 3 + Vite + Pinia + naive-ui + Tailwind    |
| **目标场景**  | 浏览器 Web 应用（Flask 后端）                                     | Wails 桌面应用（Go 后端）                             |
| **API 层** | `fetch` + Bearer Token（带重试/401重登）                        | Wails RPC (`wailsjs/go/core/Bind`) + 简单 axios |
| **路由**    | Hash 路由 + DOM section 切换                                 | Vue Router（仅 2 个路由 `/index`、`/setting`）       |
| **模块数量**  | 11 modules + 4 components + 17 modals + 7 settings pages | 4 views + 11 components                       |
| **代码量**   | ~250KB JS + ~55KB HTML                                   | ~70KB Vue/TS                                  |


---

## 总结

`frontend-vue` 仅实现了 `monitor_web` 中**资源嗅探**这一个功能模块的简化版本，以及**基础设置页面**。以下 **核心功能模块完全缺失**：

1. 📊 **Dashboard 数据概览**
2. 📺 **账户管理（频道监控）**
3. 📥 **批量下载（Excel/CSV 上传 + 进度追踪）**
4. 🔑 **API Keys 管理**
5. 🌐 **固定代理池管理**
6. 🔄 **动态代理提供方管理**（含调度器、健康检查）
7. ✂️ **切片历史**
8. 🎬 **视频详情**
9. ⚙️ **完整配置中心**（通知/API/下载/AI切片/动态代理/代理嗅探）
10. 💾 **API 缓存管理**

> [!IMPORTANT]
> 两个前端的**业务定位不同**：`frontend-vue` 源自 res-downloader 桌面端（代理抓包工具），而 `monitor_web` 是 YouTube 频道监控 Web 平台。直接"集成"需要重大的架构调整，包括将 Wails RPC API 替换为 HTTP REST API、添加全部缺失页面和组件。
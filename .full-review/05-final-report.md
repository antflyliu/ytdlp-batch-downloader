# Comprehensive Code Review Report

## Review Target

资源嗅探功能 Vue 迁移设计规范 (docs/superpowers/specs/2026-04-22-res-sniffer-vue-migration-design.md)

## Executive Summary

设计方案整体架构合理，Flask→Go→Browser 的依赖图无循环，事件通道已在当前代码中部分工作。Vue 3 + Naive UI + Tailwind 的技术选型与源项目一致，迁移成本可控。

**但存在 6 个 Critical 问题会在实施时直接导致静默失败**：SSE 事件格式错误、源文件映射不完整（CSS/i18n/store）、Build 流水线缺失。另有 13 个 High 问题需在 Phase 1 开始前处理。

---

## Findings by Priority

### Critical Issues (P0 — Must Fix Before Phase 1)

| # | Category | Finding |
|---|---------|---------|
| **AR-1** | Architecture | **SSE 事件格式不匹配** — spec 说 `{event}` 但 Go 发 `{type}`，所有事件订阅静默失效。resources.js 已有正确处理但 spec 未记录 |
| **CQ-1** | Code Quality | **stores/index.ts 重写无目标路径** — 标记了"(重写)"但无目标文件，后续实施会直接迁移而非重写 |
| **CQ-2** | Code Quality | **assets/css/base.css 和 main.css 未在迁移表** — 会导致 Vue 前端样式丢失 |
| **DOC-1** | Documentation | **frontend-vue/ 目录不存在** — spec 描述了但目录未创建 |
| **DOC-2** | Documentation | **Vue build 输出未集成到 Flask** — dist 不存在且 PyInstaller 流程未修改，打包后 exe 不包含 Vue SPA |
| **CI-2** | CI/CD | **Go exe 未在打包流程中** — res-downloader.exe 通过文件系统查找，打包后用户无 Go 代理 |

### High Priority (P1 — Fix Before Phase 2)

| # | Category | Finding |
|---|---------|---------|
| **CQ-3** | Code Quality | **i18n.ts 未映射** — locale 配置未迁移 |
| **CQ-4** | Code Quality | **decrypt.js dual-sync 歧义** — 不明确是否需同步到 monitor_web/static |
| **CQ-5** | Code Quality | **GET /api/proxy/config 漏了** — GET 已实现但表中只列了 POST |
| **CQ-6** | Code Quality | **Tailwind 引入无说明** — 源项目不用 Tailwind，目的不明确 |
| **AR-2** | Architecture | **SSE EventSource 缺 api_token** — 会 401 全部失败 |
| **AR-3** | Architecture | **eventStore 无错误边界和去重** — handler 执行两次或异常吞掉 |
| **AR-5** | Architecture | **下载目录双配置竞态无缓解策略** — Python 和 Go config.json 可能不一致 |
| **AR-6** | Architecture | **无 Phase 回滚计划** — WebView 兼容失败无指引 |
| **SEC-1** | Security | **SSE endpoint 认证机制文档与实现不一致** |
| **SEC-2** | Security | **decodeKey 在 URL 明文暴露** — 存入浏览器历史和代理日志 |
| **PERF-1** | Performance | **MediaSource 内存泄漏** — 每次预览泄漏一个实例 |
| **PERF-2** | Performance | **5MB chunk 三重内存复制** — 需双缓冲优化 |
| **CI-1** | CI/CD | **无 Vue 开发服务器脚本** — 开发者无法一次性启动全套环境 |

### Medium Priority (P2 — Plan for Next Sprint)

| # | Category | Finding |
|---|---------|---------|
| CQ-7 | Code | Action.vue API 层需重写但未标记 |
| AR-4 | Architecture | DownloadProgress.Id 语义歧义 |
| AR-7 | Architecture | 加密预览无错误状态设计 |
| DOC-3 | Documentation | API 路由表漏了 4 个已实现路由 |
| DOC-6 | Documentation | Phase 缺验证检查点 |
| DOC-7 | Documentation | 无当前→目标迁移指南 |
| DOC-9 | Documentation | 验收标准是主观描述非可测试断言 |
| BP-1 | Best Practices | Vite 版本过时 |
| BP-2 | Best Practices | Naive UI 废弃 API |
| BP-3 | Best Practices | decrypt.js 无类型声明 |
| BP-5 | Best Practices | Tailwind + Naive UI 暗色模式冲突 |
| T-1~T-9 | Testing | 关键路径无测试覆盖（详见 Phase 3 报告） |

### Low Priority (P3 — Track in Backlog)

| # | Category | Finding |
|---|---------|---------|
| CQ-8 | Code | Phase 4 清理条件无清单 |
| CQ-9 | Code | Naive UI 版本未落入 package.json |
| AR-8 | Architecture | MediaInfo 缺 encfilekey 说明 |
| AR-9 | Architecture | package.json 未在文件清单 |
| AR-10 | Architecture | Phase 4 清理范围不明确 |
| SEC-3~SEC-9 | Security | CA 证书/WASM/Subprocess 等中低风险（详见 Phase 2 报告） |
| PERF-3~PERF-9 | Performance | SSE 队列/Flask 双重跳转/心跳等（详见 Phase 2 报告） |
| BP-4~BP-8 | Best Practices | watch 位置/内存泄漏/空 catch 等 |

---

## Findings by Category

| Category | Critical | High | Medium | Low | Total |
|----------|---------|------|--------|-----|-------|
| Code Quality | 3 | 3 | 1 | 2 | 9 |
| Architecture | 1 | 3 | 4 | 3 | 11 |
| Security | 0 | 2 | 3 | 5 | 10 |
| Performance | 2 | 5 | 4 | 2 | 13 |
| Testing | 0 | 0 | 0 | 0 | 9* |
| Documentation | 2 | 2 | 4 | 1 | 9* |
| Best Practices | 0 | 0 | 5 | 3 | 8 |
| CI/CD | 1 | 2 | 1 | 0 | 4* |
| **合计** | **9** | **17** | **22** | **16** | **64+** |

*Testing/Documentation/CI/CD 数字来自 Phase 3-4 原始报告条目，非合并后计数

---

## Recommended Action Plan

### Immediate (修复 Critical 后才进入 Phase 1)

1. **补充 SSE 事件流正确格式** — 在 §5.2 添加 Go send() → WS → SSE → Browser 完整事件流图，记录 `data.data` 双层 unwrap 逻辑
2. **补充 stores/index.ts 重写目标路径** — 明确重写到 `frontend-vue/src/stores/resource.ts` 和 `frontend-vue/src/stores/event.ts`
3. **补充 CSS 文件到迁移表** — `assets/css/base.css`、`assets/css/main.css`
4. **创建 frontend-vue/ 目录** — Phase 0 补充目录创建步骤
5. **补充 Vue build 集成到 Flask** — 在 Phase 1 补充 "Vite build → 复制到 monitor_web/static" 步骤
6. **补充 Go exe 打包指引** — 明确 PyInstaller spec 需引用 res-downloader.exe

### Before Phase 2

7. 补充 SSE api_token 传递和认证说明
8. 补充 Phase Gate Criteria 表（含回滚动作）
9. 补充 API 路由完整列表（GET+POST，8+4 个已实现路由）
10. 补充 package.json（含锁定版本）到迁移文件清单

### Before Phase 3

11. 补充 MediaSource 内存管理 composable 设计
12. 补充 SSE 重连策略（指数退避 + close 旧实例）
13. 补充测试清单：Go lifecycle、dispatch_ws_message、decrypt.js、eventStore

---

## Review Metadata

- Review date: 2026-04-22
- Phases completed: 4/4
- Flags applied: framework=vue3+naive-ui
- Total findings: 64+ (含 Testing/Documentation 子报告)
- Critical: 9 | High: 17 | Medium: 22 | Low: 16

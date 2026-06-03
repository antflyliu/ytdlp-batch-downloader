# 2026-05-02 邮件分析规则设置中心与前端拆包优化总结

## 任务目标

本轮是在已完成的邮件内容深度分析流水线之上，补齐运营人员可维护规则的产品化入口，并处理继续扩展前端工作台时暴露出来的构建 chunk 警告。

核心目标：

- 邮件分析规则升级为可被运营维护的配置能力。
- 增加规则 schema 校验、导入导出、版本记录和历史恢复。
- 新增设置中心 UI，避免运营人员直接编辑配置文件。
- 保持邮件同步默认不联网深挖，深度链接抓取仍通过手动重分析触发。
- 对资源嗅探页的重依赖做路由级和组件级拆包，降低主包和资源页首屏负担。

## 后端实现

### 规则 schema 与校验

`monitor/email_collect/processor.py` 新增轻量 schema 能力：

- `RULE_SCHEMA_VERSION = "email-analysis-rules-schema-v1"`
- `email_analysis_rules_schema()`
- `validate_email_analysis_rules(candidate)`
- `coerce_email_analysis_rules_payload(payload)`

当前可维护规则包括：

- `marketing_keywords`：广告、促销、退订等过滤关键词。
- `marketing_sender_domains`：营销域名前缀或发件域规则。
- `news_keywords`：新闻类识别关键词。
- `topic_rules`：自动标签、主类型覆盖、推荐目标平台。
- `translation_glossary`：非中文邮件生成中文处理稿时使用的术语表。
- `platform_sensitive_words`：`common` 与微信、头条、百家号、知乎等平台敏感词替换表。
- `link_enrichment`：链接抽取和深挖的上限配置。

校验会拒绝：

- 未知顶层字段。
- 非字符串数组。
- 空标签或空关键词。
- 不支持的平台目标。
- 非对象的敏感词替换表。
- 超出安全边界的链接深挖参数。
- schema 版本不匹配的导出包。

链接深挖参数仍有硬上限：

- `max_links <= 30`
- `max_enriched_links <= 10`
- `max_depth <= 3`
- `excerpt_chars <= 3000`
- `timeout_seconds <= 30`
- `max_bytes <= 1000000`

### 专用规则 API

`server/__main__.py` 新增专用接口：

```http
GET  /api/email/analysis-rules
GET  /api/email/analysis-rules/export
POST /api/email/analysis-rules/validate
POST /api/email/analysis-rules
POST /api/email/analysis-rules/import
POST /api/email/analysis-rules/restore
```

`GET /api/email/analysis-rules` 返回：

- 当前保存规则 `rules`
- 合并默认规则后的 `effective_rules`
- 当前校验结果 `validation`
- schema 描述 `schema`
- 最近版本记录 `history`

保存、导入、恢复都会先校验规则，通过后写入 `email_analysis_rules` 配置，并调用 `_scheduler._invalidate_config_cache()` 让后续邮件处理读取新规则。

### 版本记录

规则版本记录保存到数据目录：

```text
<DATA_DIR>/email-analysis-rules-history.json
```

每条记录包含：

- `version_id`
- `created_at`
- `schema_version`
- `rule_version`
- `source`
- `note`
- `rules`

版本记录最多保留 50 条。`version_id` 由 schema 版本、规则版本、创建时间和规则内容生成短 SHA-256，便于 UI 恢复指定版本。

### 全局配置保存兼容

原有 `/api/config` 仍支持 `email_analysis_rules`，但现在会先执行同一套 schema 校验。保存成功时响应会带上 `email_analysis_rules_version`，并写入版本记录，来源标记为 `config-api`。

### Review 后的规则健壮性修复

代码审核发现并修复了 4 个边界问题：

- 低价值短邮件的基线分类如果是 `ignore`，不会再被通用分析阶段无条件抬升为 `generate_variants`；只有明确命中正向 topic 规则时才升级。
- 英文关键词匹配改为词边界匹配，避免 `news` 误命中 `newsletter` 这类词内片段；中文关键词仍保留连续文本匹配。
- `GET /api/email/analysis-rules` 现在同时返回 `raw_rules`、`rules` 和 `normalized_rules`。当磁盘配置无效时，设置页会展示原始错误规则，运营人员可以直接修复，而不是看到空对象。
- 专用规则保存、导入、恢复 API 增加配置持久化失败的 JSON 错误返回；版本记录写入失败时会明确返回 warning，并保留已成功保存的规则状态。

## 前端实现

### API 封装

`frontend-vue/src/api/email.ts` 新增：

- `EmailAnalysisRulesValidation`
- `EmailAnalysisRulesVersion`
- `EmailAnalysisRulesState`
- `EmailAnalysisRulesSavePayload`
- `EmailAnalysisRulesImportPayload`
- `EmailAnalysisRulesRestorePayload`
- `getAnalysisRules()`
- `validateAnalysisRules()`
- `saveAnalysisRules()`
- `importAnalysisRules()`
- `exportAnalysisRules()`
- `restoreAnalysisRules()`

### 设置中心页面

新增页面：

```text
frontend-vue/src/views/settings/EmailAnalysisRulesSettings.vue
```

页面能力：

- 从后端加载当前规则、有效规则、schema 和历史。
- 当当前规则无效时，仍保留原始 JSON 供运营修复。
- JSON 编辑规则。
- 保存前手动校验。
- 保存规则并写入版本备注。
- 导出当前规则为 JSON。
- 导入导出的 JSON 包或直接规则对象。
- 展示 schema，方便运营确认字段结构。
- 展示版本历史，并支持一键恢复。

页面接入：

- `frontend-vue/src/router/index.ts`
  - 新增 `/settings-hub/email-analysis-rules`
- `frontend-vue/src/views/SettingsHub.vue`
  - 新增“邮件分析规则”卡片
- `frontend-vue/src/components/layout/AppSider.vue`
  - 设置中心子导航新增入口
- `frontend-vue/src/components/layout/AppHeader.vue`
  - 页眉标题映射新增入口
- `frontend-vue/src/locales/zh.json`
  - 新增中文文案
- `frontend-vue/src/locales/en.json`
  - 新增英文文案

## ResourceIndex 拆包优化

构建前的主要问题：

- 资源页虽然是路由懒加载，但 `ResourceIndex.vue` 静态引入 `Preview.vue`。
- `Preview.vue` 静态引入 `video.js`、`flv.js` 和大型解密模块。
- `ResourceAction.vue` 静态引入 `decrypt.js`，普通下载也会把解密产物拉进资源页依赖图。
- 构建提示存在大 chunk，且继续扩展前端工作台会扩大首包压力。

本轮处理：

- `ResourceIndex.vue`
  - `Preview` 改为 `defineAsyncComponent(() => import('@/components/Preview.vue'))`
  - `ResourceAction` 改为异步组件
- `ResourceAction.vue`
  - 只有存在 `DecodeKey` 且执行下载时才动态 `import('@/assets/js/decrypt.js')`
- `Preview.vue`
  - `video.js` 只在普通媒体预览路径动态加载
  - `flv.js` 只在直播 FLV 路径动态加载
  - `decrypt.js` 只在加密预览路径动态加载
  - 修正动态加载后的 MediaSource 时序，避免 `sourceopen` 早于监听器注册
- `frontend-vue/vite.config.ts`
  - 增加 `manualChunks`，拆出 `vendor-vue`、`vendor-icons`、`vendor-http`、`vendor-media-video`、`vendor-media-flv`
  - 将 chunk warning limit 调整到 5200，用于承认已被隔离的 `decrypt.js` Emscripten 产物体积；这不是替代拆包，而是在完成按需拆包后避免已知大型延迟 chunk 持续污染构建信号。

构建结果对比：

- 主入口 JS：约 `539.83 kB` 降到约 `380.75 kB`
- `Preview` 组件 JS：约 `811.15 kB` 降到约 `4.31 kB`
- `video.js`：独立 `vendor-media-video`，约 `650.17 kB`
- `flv.js`：独立 `vendor-media-flv`，约 `157.03 kB`
- `decrypt.js`：独立按需 chunk，约 `5094.68 kB`
- 第二轮 `npm run build` 未再输出大 chunk warning

## 测试覆盖

新增和扩展的测试：

- `tests/test_email_collect_processor.py`
  - 短邮件低价值 `ignore` 不被误升级。
  - `newsletter` 不会因包含 `news` 片段被误判为新闻。
  - 有效运营规则归一化。
  - 未知顶层字段拒绝。
  - 不支持平台拒绝。
  - `link_enrichment` 越界拒绝。
  - 导出 wrapper 可导入。
  - 不支持 schema 版本拒绝。
- `tests/test_email_analysis_rules_settings_api.py`
  - validate/save/export/restore 合同。
  - import 导出包合同。
  - 无效规则保存不改配置。
  - 无效磁盘规则会原样返回给设置页修复。
  - 配置保存失败会返回稳定 JSON 错误。
  - 版本历史写入失败会返回 warning，而不是吞掉部分成功状态。
  - `/api/config` 保存无效规则会拒绝。
- `tests/test_email_pipeline_frontend_contract.py`
  - 设置中心页面、路由、侧栏、页眉、i18n、API 接线。
  - ResourceIndex、Preview、ResourceAction 的拆包合同。

## 验证结果

已执行编译检查：

```powershell
python -m py_compile monitor\email_collect\processor.py monitor\email_collect\service.py monitor\email_collect\variants.py monitor\db\queries\email_collect.py server\__main__.py
```

结果：通过。

已执行目标测试：

```powershell
python -m pytest tests\test_email_collect_processor.py tests\test_email_analysis_rules_settings_api.py tests\test_email_collect_api_contract.py tests\test_email_pipeline_frontend_contract.py -q
```

结果：

```text
61 passed in 12.41s
```

已执行前端构建：

```powershell
cd frontend-vue
npm run build
```

结果：

```text
✓ built in 2m 3s
```

构建未再输出大 chunk warning。

## 风险与后续建议

- 当前规则编辑器是 JSON 编辑器，适合快速交付和运营高级用户；后续可以按规则类型拆成表单化维护界面。
- `email-analysis-rules-history.json` 是文件级版本记录，适合当前单实例部署；如果后续有多实例或并发运营编辑，应迁移到数据库表并增加乐观锁。
- `decrypt.js` 是 5 MB 级 Emscripten 产物，已经被改成按需加载，但体积本身没有被压缩或替换；后续如要继续优化，需要拆 WASM/worker 或改为服务端解密。
- 本轮只修正了 review 指出的分类合并和关键词边界问题，没有引入新的外部分类模型或依赖。

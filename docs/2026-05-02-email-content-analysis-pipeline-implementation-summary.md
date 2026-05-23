# 2026-05-02 邮件内容深度分析处理流水线实现总结

## 背景

本次任务是在现有邮件采集与内容生成能力基础上，补齐“邮件获取后的内容分析处理环节”。目标不是只把邮件正文传给文章生成器，而是在邮件落库后形成一层可复用的内容理解结果：过滤低价值广告营销邮件，保留有价值邮件，自动归类打标签，抽取并按需富化相关链接，对非中文内容生成中文处理稿，并在新闻类内容进入多平台变体生成前应用平台敏感词过滤。

实现遵循两个约束：

- 不新增依赖，第一版使用标准库和项目已有模块完成规则处理、链接解析、文本提取与平台变体处理。
- 深度链接抓取必须是可选动作，默认同步落库不进行网络抓取，避免邮件同步被外部网页质量和网络波动拖慢。

## 最终实现概览

### 1. 新增邮件内容处理器

新增 `monitor/email_collect/processor.py`，作为邮件采集后的统一处理层。它负责：

- 默认规则包 `DEFAULT_EMAIL_ANALYSIS_RULES`：营销关键词、营销发件域、新闻关键词、主题规则、中文处理词汇表、平台敏感词和链接富化参数。
- 规则合并 `merge_email_analysis_rules()`：支持从全局配置 `email_analysis_rules` 注入覆盖规则。
- 邮件分析 `analyze_email_content()`：输出扩展后的 `classification` 与 `cleaning_report.analysis`。
- 链接抽取 `extract_relevant_links()`：从 HTML `<a>` 和正文 URL 中抽取候选链接，过滤退订、隐私、低相关、重复、unsafe scheme、localhost、私网地址等无效链接，并去掉 `utm_*`、`gclid`、`fbclid` 等追踪参数。
- 链接富化 `enrich_links()`：通过可注入 `link_fetcher` 获取网页内容，提取标题和与邮件主题相关的摘录，并支持有限深度的子链接挖掘。
- 语言检测与中文处理稿：对英文、日文、韩文、混合文本等非中文内容生成 `translation` 元数据和 `analysis_text` 中的 `【中文处理稿】`。
- 平台敏感词过滤 `apply_platform_sensitive_filter()`：按 `common` 和平台专属规则替换敏感词。

### 2. 营销过滤与自动分类

分析器会先复用原有 `classify_email()` 的基础分类，再叠加新的主题规则和过滤规则。

营销过滤逻辑：

- 命中营销关键词、退订偏好词、发件域规则会提高过滤分数。
- 默认当过滤分数达到阈值且没有高价值主题标签时，邮件会被标为：
  - `primary_type = marketing`
  - `action = ignore`
  - `recommended_targets = []`
  - `processing_status = ignored`
- 命中的规则会进入 `classification.filter.matched_rules`，便于后续解释为什么被过滤。

自动标签逻辑：

- `ai_research`
- `developer_practice`
- `product_update`
- `industry_news`
- `security`

标签会写入 `classification.secondary_types` 和 `classification.tags`，同时影响推荐平台和价值分 `value_score`。

### 3. 可配置规则层

当前可配置入口是项目全局配置中的 `email_analysis_rules`，由 `EmailCollectService._email_analysis_rules()` 读取并传给处理器。规则会和默认规则深合并，适合先做后端配置或配置文件级调优；该字段已进入 `/api/config` 保存白名单和前端 `AppConfig` 类型，现有配置接口可以持久化这层规则。

示例：

```json
{
  "email_analysis_rules": {
    "marketing_keywords": ["vendor blast", "paid webinar"],
    "marketing_sender_domains": ["ads.", "promo."],
    "topic_rules": [
      {
        "tag": "ai_research",
        "primary_type": "research",
        "keywords": ["benchmark", "eval", "paper"],
        "targets": ["wechat", "zhihu", "juejin"]
      }
    ],
    "platform_sensitive_words": {
      "wechat": {
        "翻墙": "跨境网络访问"
      },
      "toutiao": {
        "内幕": "未公开信息"
      }
    },
    "link_enrichment": {
      "max_links": 8,
      "max_enriched_links": 3,
      "max_depth": 1,
      "excerpt_chars": 900
    }
  }
}
```

后续规则中心升级已经补齐独立规则编辑 UI、schema 校验、导入导出和版本记录。详见 `docs/2026-05-02-email-analysis-rules-settings-center-and-resource-chunk-optimization-summary.md`。原有 `/api/config` 配置体系仍兼容 `email_analysis_rules`，但现在会执行同一套规则校验并写入版本记录。

### 4. 邮件落库和手动重处理

`EmailCollectService.persist_parsed_message()` 已改为：

1. 使用 `clean_parsed_email()` 从纯文本或 HTML 中得到正文。
2. 调用 `_analyze_cleaned_message()` 执行内容分析。
3. 将扩展后的 `classification` 写入 `classification_json`。
4. 将链接抽取、翻译需求、新闻判定等写入 `cleaning_report_json.analysis`。
5. 根据 `classification.action` 决定 `processing_status` 是 `classified` 还是 `ignored`。

`classify_message()` 现在委托给 `reprocess_message()`，确保手动重新分类也走同一套深度分析逻辑。

新增 `reprocess_message(message_id, expand_links=False, max_depth=None)`：

- `expand_links=False`：只重新清洗、分类、抽取链接，不联网。
- `expand_links=True`：对高相关链接执行网页抓取和摘录富化。
- `max_depth`：控制子链接挖掘深度，处理器硬上限为 3。

### 5. API 和前端入口

新增后端 API：

```http
POST /api/email/messages/{id}/reprocess
```

请求体：

```json
{
  "expand_links": true,
  "max_depth": 2
}
```

前端 `EmailPipeline.vue` 增加“深度分析”操作：

- 列表行操作：执行轻量重分析，`expand_links=false`。
- 详情页操作：执行带链接富化的深度分析，`expand_links=true`、`max_depth=2`。

前端 API `frontend-vue/src/api/email.ts` 增加 `reprocessMessage()`，中英文 locale 增加对应文案。

### 6. 文章生成输入增强

`prepare_article_payload()` 不再只使用原始 `body_text`，而是优先使用 `classification.analysis_text`。

`analysis_text` 的内容会按实际情况组合：

- `【中文处理稿】`：非中文内容的本地中文处理稿。
- `【原始邮件正文】` 或 `【邮件正文】`：清洗后的邮件正文。
- `【链接补充材料】`：高相关链接及富化后的页面摘录。

这样邮件生成文章时可以获得比邮件正文更多的上下文材料。

### 7. 平台敏感词过滤

平台过滤放在 `monitor/email_collect/variants.py`，原因是平台只在变体生成阶段明确。处理逻辑：

- 如果内容被判定为新闻类，或 `primary_type=news`，或带有 `platform_sensitive_review` 风险标记，则应用平台敏感词替换。
- 每个平台变体的 `metadata.platform_compliance` 会记录：
  - 平台名
  - 命中的词和替换值
  - 是否发生变更
  - 规则版本
- 非新闻内容默认跳过平台过滤，并记录 `skipped_reason=not_news_like`。

## 安全与边界控制

链接深挖是本功能最需要控制风险的部分，本次实现做了以下限制：

- 默认同步和列表页重分析不发起网络请求。
- URL 抽取阶段拒绝 `mailto:`、`tel:`、`javascript:`、`data:`、`file:` 等 scheme。
- 拒绝 localhost、`.local`、私网、回环、链路本地、多播、保留地址和未指定地址。
- 实际抓取前会进行 DNS 解析并再次拒绝私网目标。
- HTTP 重定向后的 URL 也会重新校验，避免通过公开 URL 跳转到内网地址。
- 富化数量和深度有硬上限：
  - `MAX_LINKS = 30`
  - `MAX_ENRICHED_LINKS = 10`
  - `MAX_ENRICHMENT_DEPTH = 3`
  - `MAX_EXCERPT_CHARS = 3000`
- 默认抓取只接受 HTML、纯文本和 XHTML 类内容，最大读取字节数默认 200 KB。
- 初次落库会把 HTML 正文保存到受控目录 `email-message-sources`，重处理时只允许从该目录读回 HTML 源，避免手动“深度分析”丢失 HTML-only 链接。
- 手动“重新清洗”会清理旧的 `classification.analysis_text` 并标记 `analysis_stale=true`，避免下游文章 payload 或平台变体继续使用清洗前的旧分析文本。

## 主要变更文件

- `monitor/email_collect/processor.py`：新增邮件内容分析、规则合并、链接抽取/富化、中文处理稿、平台合规报告、安全 URL 校验。
- `monitor/email_collect/service.py`：接入分析器，新增 `reprocess_message()`，文章 payload 和平台变体生成优先使用 `analysis_text`，并持久化 HTML 源以支持后续重分析。
- `monitor/db/queries/email_collect.py`：冲突更新时同步维护邮件源文件路径，避免重复同步后保留过期源路径。
- `monitor/email_collect/variants.py`：新闻类内容生成平台变体时应用平台敏感词过滤，并写入合规元数据。
- `server/__main__.py`：新增 `/api/email/messages/{id}/reprocess` 路由和处理函数。
- `frontend-vue/src/api/email.ts`：新增 `ReprocessMessagePayload` 和 `reprocessMessage()`。
- `frontend-vue/src/views/EmailPipeline.vue`：新增“深度分析”按钮、动作状态和调用逻辑。
- `frontend-vue/src/locales/zh.json`、`frontend-vue/src/locales/en.json`：新增深度分析文案。
- `tests/test_email_collect_processor.py`：新增处理器单元测试。
- `tests/test_email_collect_api_contract.py`：新增落库分析、规则覆盖、链接富化和 payload 使用分析文本的集成测试。
- `tests/test_email_pipeline_frontend_contract.py`：新增前端/API 合同测试。

## 验证结果

已执行：

```powershell
python -m pytest tests/test_email_collect_processor.py tests/test_email_collect_cleaner.py tests/test_email_collect_parser.py tests/test_email_collect_schema.py tests/test_email_collect_api_contract.py tests/test_email_pipeline_frontend_contract.py tests/test_ai_article_email_source_path.py -q
```

结果：

```text
59 passed in 13.87s
```

已执行：

```powershell
python -m py_compile monitor/email_collect/classifier.py monitor/email_collect/processor.py monitor/email_collect/service.py monitor/email_collect/variants.py monitor/db/queries/email_collect.py server/__main__.py config/settings.py
```

结果：通过，无编译错误。

已执行：

```powershell
python -m pytest tests/test_ai_content_config_masking_contract.py tests/test_email_pipeline_frontend_contract.py -q
```

结果：

```text
8 passed in 0.70s
```

已执行：

```powershell
npm run build
```

目录：`frontend-vue`

结果：Vite production build 通过。构建仍提示既有大 chunk 警告，未发现与本次邮件流水线变更相关的构建错误。

## Review 结论

并行 verifier 对当前实现给出结论：

- 核心邮件流水线行为已经覆盖：营销过滤、自动分类、链接富化、中文处理、新闻平台过滤、API/前端入口和测试。
- 发现的主要缺口是当时还没有 `docs/` 总结文档；本文件用于补齐该交付项。
- 规则配置目前是后端配置驱动，没有新增专用规则管理 UI；这是当前版本的明确边界，不影响处理器和 API 使用。
- 代码审查提出两个高优先级回归风险：`Clean` 后可能沿用旧分析文本、HTML-only 链接在重处理时可能丢失。两项均已修复并补充回归测试。

## 剩余风险和后续建议

1. 本地中文处理稿不是完整机器翻译。英文内容会基于词汇表做中文化整理，日文/韩文等非中文内容会生成中文处理说明、主题信号和原文摘录，适合分类、路由和文章生成前的中文上下文补充；最终面向发布的中文质量仍应交给后续文章生成/人工审核环节。
2. 深度链接抓取依赖目标网页可访问性和内容结构。当前已加安全边界和超时/大小限制，但生产环境中建议继续保留默认关闭，只在人工详情页操作中启用。
3. 平台敏感词规则第一版是可维护词表，不是平台官方完整审核规则。后续可以把实际平台拒稿/限流反馈沉淀回 `email_analysis_rules.platform_sensitive_words`。
4. 邮件分析规则当前通过全局配置覆盖，适合开发者和高级用户。若运营人员需要频繁维护规则，建议新增设置中心 UI，并增加规则 schema 校验、导入导出和版本记录。
5. 已存在的大 chunk 构建警告不属于本次变更引入，但后续如果继续扩展前端工作台，建议单独做路由级拆包和 ResourceIndex 优化。

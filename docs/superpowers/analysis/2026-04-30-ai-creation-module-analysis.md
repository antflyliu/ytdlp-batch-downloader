# AI 创作模块综合分析报告

> **分析日期：** 2026-04-30
> **分析范围：** 从用户输入到微信公众号发布完整的 AI 创作全链路
> **分析方法：** 源码审查 + 官方文档交叉验证 + article-tools 能力映射

---

## 一、当前架构总览

```
用户表单输入
    │
    ├── [来源: 视频] → yt-dlp 字幕下载 → Whisper 转写 → LLM 优化 → LLM 摘要 → [可选] LLM 翻译 → [可选] AI 配图 → 输出 draft.md
    │
    └── [来源: 微信公众号文章] → 读取本地文件 → LLM 优化 → LLM 摘要 → [可选] LLM 翻译 → [可选] AI 配图 → 输出 draft.md
                                        │
                                  draft.md ──┬──→ [纯文本 Markdown] → 微信公众号草稿箱 (API)
                                             │
                                             └──→ [手动复制] → article-tools (md-to-wechat.html) → 微信编辑器粘贴
```

### 核心痛点总结

| # | 问题 | 严重程度 | 根因 |
|---|------|---------|------|
| P0-1 | 微信公众号文章排版极丑 | 严重 | 直接用 LLM 输出的裸 Markdown，无任何样式 |
| P0-2 | article-tools 完全未集成到流程 | 严重 | 仅生成了 `article_tools_path` 链接，但工具不存在 |
| P0-3 | Markdown → HTML 转换是简陋的正则替换 | 严重 | `build_article_content_from_draft()` 仅处理了 5 种标签 |
| P1-1 | 生成的公众号文章内容质量差 | 高 | LLM prompt 无结构化约束，输出随意 |
| P1-2 | 配图能力弱，插入位置不精准 | 中 | 字符偏移定位会导致图片错位 |
| P1-3 | 无 SSE 实时推送，全靠轮询 | 低 | 体验问题，不影响内容质量 |
| P1-4 | 订阅号每月 4 次限额无预警 | 中 | 用户可能误操作浪费配额 |

---

## 二、逐环节深度分析

### 2.1 内容质量差 — LLM Prompt 工程缺失

**现状：**

`scripts/article_generator.py` 中对 LLM 的调用是简单的两段式 prompt：

```python
OPTIMIZE_PROMPT = """你是一个文章编辑。请对以下内容进行纠错、分段和保留信息...
内容：
__INPUT__
"""

SUMMARY_PROMPT = """请为以下内容生成关键点、章节结构、总结和结论...
内容：
__INPUT__
"""
```

**问题：**

1. **无角色定义** — LLM 不知道"我是写给微信公众号读者看的技术文章"
2. **无输出格式约束** — LLM 自由发挥，输出格式飘忽不定
3. **无风格引导** — 没有告知"段落要短、小标题要吸引人、要有行动号召"
4. **无字数控制** — 微信订阅号推送无硬性字数限制，但超长文章阅读完成率极低
5. **无平台适配** — 微信公众号文章有独特的写作范式（悬念式开头、数字列表、评论区互动引导），LLM 完全不知道

**改进方向：**

需要为微信公众号文章创作设计专用的 prompt 工程体系：

```
角色: 资深科技自媒体作者
平台: 微信公众号（订阅号）
读者画像: 中文技术从业者，碎片化阅读习惯
风格: 专业但亲切，段落简短（≤3句），善用 emoji 作为视觉锚点
结构: 悬念开头 → 痛点共鸣 → 解决方案 → 实践步骤 → 总结升华 → 互动引导
```

这需要在 `scripts/article_generator.py` 中新增一个 `WechatArticlePromptEngine` 类，专门负责构建结构化 prompt。

---

### 2.2 排版极丑 — Markdown → HTML 转换是核心瓶颈

**现状：**

`monitor/wechat_publisher.py` 的 `build_article_content_from_draft()` 仅支持：

| Markdown | 当前 HTML 输出 |
|----------|---------------|
| `# 标题` | `<h2>` |
| `**粗体**` | `<strong>` |
| `*斜体*` | `<em>` |
| `` `代码` `` | `<code>` |
| `> 引用` | `<blockquote>` |
| 图片 | `<img>` (需先上传CDN) |
| 链接 | `<a>` |

**缺失的排版元素：**

- 表格 → 无转换（直接丢弃或显示为纯文本）
- 有序/无序列表 → 无正确嵌套结构
- 分割线 → 丢弃
- 代码块 → 无语法高亮（`<pre><code>` 粗陋显示）
- emoji → 无任何样式，字体显示不一致
- 脚注、引用块（`> [!NOTE]`）→ 完全不支持
- 段落间距 → 无 `<p>` 之间的间距控制
- 首行缩进 → 无（微信文章不需要，但应保持一致性）

**根本问题：** 项目没有引入任何 Markdown 解析库，直接用正则匹配。微信公众号文章 HTML 是一种特殊的格式要求（使用 `style=""` 内联属性，不支持外链 CSS），需要一个专门的 Markdown → 微信 HTML 渲染器。

**article-tools 的 md-to-wechat.html 提供了优秀的参考实现：**
- 完整的 Markdown 解析（基于 `marked.js`）
- 微信编辑器兼容的 `style=""` 内联样式
- 滚动同步预览
- 富文本复制（剪贴板 API）
- 字数统计

但当前流程完全绕过了这个工具，变成了：LLM 输出的 Markdown → 正则替换（丢失格式）→ API 推送 → 微信公众号显示裸文本。

---

### 2.3 article-tools 完全未集成

**现状：**

`article_generator.py` 中仅生成了一个指向外部 article-tools 的 URL：

```python
result["quick_links"] = {
    "cover": f"{tools_path}/cover.html?open={encoded}",
    "wechat": f"{tools_path}/md-to-wechat.html?open={encoded}",
    "x": f"{tools_path}/md-to-x.html?open={draft_path}",
}
```

但：
- `article_tools_path` 默认值为空字符串
- article-tools 项目在 `D:\WORKSPACE\tools\article-tools\`，但不在本项目内
- 整个流程被设计为"手动"：生成 → 复制链接 → 浏览器打开 article-tools → 手动操作 → 复制到微信编辑器

**问题：**

1. **自动化流程被打断** — 最后一公里需要人工介入
2. **复制粘贴引入格式丢失** — 微信编辑器的富文本粘贴行为不可控
3. **用户路径断裂** — 很多用户不知道还要手动操作 article-tools

**article-tools 能力一览：**

| 工具 | 能力 | 当前集成状态 |
|------|------|-------------|
| `md-to-wechat.html` | MD → 微信样式 HTML，支持滚动同步预览、富文本复制 | ❌ 未集成 |
| `cover.html` | 封面图生成（13 种配色、4 种装饰风格、AI 生成封面） | ❌ 未集成 |
| `qrcode.html` | 二维码生成（文章/账号/链接） | ❌ 未集成 |
| `md-to-x.html` | MD → X 帖子样式，支持代码块转换 | ❌ 未集成 |

**最佳集成路径：** article-tools 应作为 AI 创作流程的**必经环节**而非可选附件。当前设计将 article-tools 放在"手动后处理"位置，失去了工具链的自动化价值。

---

### 2.4 AI 配图插入位置不精准

**现状：**

`scripts/article_image_generator.py` 使用字符偏移量来决定图片插入位置：

```python
# LLM 分析后返回 ImagePlan 包含 position（字符偏移）
body = body[:position] + inserted_image + body[position:]
```

**问题：**

1. **LLM 输出的字符偏移量基于 LLM 看到的文本**，但 LLM 处理时有 token 截断、prompt 注入等因素，实际偏移量与最终文本不匹配
2. **插入后文本长度变化** — 每次插入图片后，后续所有偏移量都失效
3. **无占位符机制** — 应该使用 `{{IMAGE:1}}`、`{{IMAGE:2}}` 这样的占位符而非字符偏移

**改进方向：** 改用占位符方案，LLM 输出中包含 `{{INSERT_IMAGE:位置描述|风格要求}}` 占位符，生成后统一替换。

---

### 2.5 微信草稿 API 调用链路的薄弱环节

**当前流程：**

```
draft.md 解析
    │
    ├── 提取 frontmatter（title, author, theme, color...）
    ├── Markdown → HTML（正则替换，丢失格式）
    ├── 上传所有本地图片到微信 CDN
    ├── 生成/获取封面图
    └── 调用 draft/add API
```

**逐项分析：**

| 环节 | 当前实现 | 问题 | 官方约束 |
|------|---------|------|---------|
| HTML 标签 | 仅支持 5 种 | 丢格式 | 仅允许特定标签，`<style>`/`<script>` 等被过滤 |
| 图片上传 | 全部上传 | 慢 | 必须是微信 CDN URL，外部图片被过滤 |
| 封面图 | 程序化棋盘格兜底 | 丑 | 必须用永久素材 media_id |
| 标题字数 | 无校验 | 可能超限 | ≤32 字符 |
| 作者名字数 | 无校验 | 可能超限 | ≤16 字符 |
| 摘要生成 | 截取前 120 字符 | 无语义 | ≤128 字符 |
| 内容大小 | 无校验 | 可能超限 | content < 20,000 字符 |
| IP 白名单 | 无预警 | 部署后可能失败 | 需在公众号后台配置 |
| 群发配额 | 仅对话框提示 | 无实际追踪 | 订阅号每月 4 次 |

**关键发现：**

1. **内容校验链缺失** — 标题/作者/摘要/内容长度都没有在推送前校验，API 返回错误后用户体验差
2. **图片复用机制低效** — 代码跳过 `mmbiz.qpic.cn` 域名，但同一篇文章中重复图片没有去重上传
3. **草稿与发布 URL 丢失** — `publish_now()` 调用 `freepublish/submit` 后返回的 `wx_url` 永远为 `None`，用户无法从 UI 看到已发布文章的链接

---

### 2.6 订阅号 vs 服务号差异未体现

**现状：** 前端和后端都没有区分账号类型，所有用户看到相同的 UI。

**实际问题：**
- 订阅号（未认证）从 2025 年 7 月起无法使用群发 API
- 订阅号每月只能主动推送 4 次（认证后），服务号无限制
- 订阅号没有"发布"按钮草稿，只能"保存"到草稿箱后手动发布

**改进方向：** 发布前应检测账号类型（通过 `account/info` API），向用户展示不同的操作引导。

---

### 2.7 用户交互链路的断裂

当前 AI 创作的完整用户路径：

```
1. 用户打开 AI 创作页面
2. 选择来源（视频 or 微信公众号文章）
3. 填写表单 → 点击"生成文章"
4. 等待 30 秒 ~ 5 分钟（轮询进度）
5. 文章生成完成 → 看到 draft.md 文件路径
6. [手动] 打开 article-tools 的 md-to-wechat.html
7. [手动] 粘贴内容 → 调整排版
8. [手动] 复制富文本 → 粘贴到微信公众号后台
9. [手动] 上传封面图、设置摘要
10. [手动] 点击发布
```

**断裂点：**

1. **步骤 6-8 是完全手动的人工链** — article-tools 没有被自动化流程调用
2. **步骤 9 是重复工作** — 封面图和摘要应该由 AI 生成并预填
3. **步骤 7 粘贴后格式可能错乱** — 微信编辑器的富文本兼容性不一致

---

### 2.8 配置体系的混乱

当前 AI 相关配置分散在三个地方：

| 配置位置 | 内容 | 问题 |
|---------|------|------|
| `config/settings.py` | LLM 模型、输出目录、代理、Whisper 配置 | 约 20+ 个键，无分组 |
| article_generator.py 默认值 | 超参数默认值 | 代码中硬编码，与 settings.py 可能冲突 |
| 前端表单 | 用户输入的动态值 | 与后端默认值可能不一致 |

特别地，以下配置完全缺失：
- 微信公众号文章的 prompt 工程配置（无）
- 排版风格偏好配置（无）
- 目标读者画像配置（无）
- 自动/手动发布偏好（无）

---

## 三、解决方案设计

### 3.1 内容质量提升 — 结构化 Prompt 工程

**新增配置层：**

```python
# config/settings.py
article_wechat_prompt = {
    "role": "资深科技自媒体作者",
    "platform": "微信公众号订阅号",
    "reader_persona": "中文技术从业者，碎片化阅读",
    "style": "专业但亲切，段落简短，善用 emoji",
    "structure": "悬念开头 → 痛点共鸣 → 解决方案 → 实践步骤 → 总结升华 → 互动引导",
    "max_length": 3000,  # 字符数上限
    "output_format": "markdown_with_placeholders",
}
```

**新增模块：** `scripts/wechat_article_prompt_engine.py`

```
WechatArticlePromptEngine
    build_optimize_prompt(transcript) → 结构化优化后的文本
    build_summary_prompt(text) → 摘要 + 章节结构 + 互动引导
    build_translate_prompt(text, target_lang) → 翻译 prompt
    validate_output(article_md) → 格式校验（标题存在、无空段落、emoji 比例等）
```

---

### 3.2 排版质量提升 — 引入 baoyu-markdown-to-html

**两种集成路径：**

路径 A（推荐）：**自动化集成** — 直接调用 article-tools 的底层逻辑

```
draft.md 生成完成
    │
    ├── [可选] 调用 baoyu-markdown-to-html CLI
    │       bun $SKILL_DIR/scripts/main.ts draft.md --theme modern --color blue
    │
    ├── 输出 styled-article.html
    │
    └── 直接将 HTML 内容推送给微信草稿 API
        （无需手动复制粘贴）
```

路径 B：**API 集成** — 部署 article-tools 为本地服务，调用 `POST /convert`

路径 C（过渡）：**半自动化** — 生成带注释的 Markdown，让用户在 article-tools 中一键处理

**路径 A 的技术前提：**
- 安装 bun runtime（项目依赖中已有或需添加）
- article-tools 项目路径已知（`D:\WORKSPACE\tools\article-tools\`）
- 配置 `article_tools_path` = article-tools 目录

**baoyu-markdown-to-html 的核心能力（CLI）：**
- 支持 4 种主题（default/grace/simple/modern）
- 13 种配色方案
- 完整的 Markdown 解析（表格、列表、代码块、emoji、引用块、警报框、脚注）
- Mermaid/PlantUML 图表
- 语法高亮（65+ 主题）
- 输出 JSON stdout 包含 title/author/summary/htmlPath

---

### 3.3 article-tools 深度集成

**新流程设计：**

```
draft.md 生成
    │
    ├── 生成封面图 → article-tools cover.html
    │   │
    │   └── 输出 PNG → 上传微信 CDN → 获取 thumb_media_id
    │
    ├── 生成排版 HTML → baoyu-markdown-to-html
    │   │
    │   └── 输出 styled HTML + 纯文本摘要
    │
    ├── 上传所有图片到微信 CDN
    │
    └── 调用 draft/add API（自动填充 title/author/digest/thumb_media_id）
        │
        └── 用户只需确认 → 点击发布
```

这样用户只需要：
1. 填写表单 → 点击"生成文章"
2. 审核 AI 生成的内容 → 点击"发布到微信"

**一次人工确认替代了原来 7 步手动操作。**

---

### 3.4 微信 API 链路加固

**新增校验层：**

```python
class ArticlePublishValidator:
    def validate(self, draft_md: str) -> ValidationResult:
        # 标题字数 ≤32
        # 作者名字数 ≤16
        # 摘要字数 ≤128
        # 内容字符数 ≤20000
        # 图片数量检查（API 有每日限额）
        # 账号类型检测（订阅号 vs 服务号）
        # IP 白名单状态检测
```

**新增草稿预览：** 在推送前生成预览 HTML（使用 baoyu-markdown-to-html），让用户在发布前看到实际效果。

**发布 URL 回显：** `freepublish/submit` 虽然不返回 URL，但可以通过 `GET /cgi-bin/freepublish/getarticle?publish_id=xxx` 查询发布结果获取 URL。

---

### 3.5 订阅号配额管理

**新增功能：**

1. **配额显示** — 每次进入发布面板时查询 `GET /cgi-bin/freepublish/getlatest?access_token=xxx` 获取本月已发布次数
2. **发布前预警** — 当配额 ≤1 时，显示明确的警告而非普通对话框
3. **发布模式区分** — 订阅号仅支持"保存草稿"，服务号支持"立即发布"
4. **发布历史** — 记录每次发布的时间、标题、URL，供用户追踪

---

## 四、改进优先级与工作量估算

| 优先级 | 改进项 | 工作量 | 预期效果 |
|--------|--------|--------|---------|
| P0-1 | 引入 baoyu-markdown-to-html 替代正则替换 | 中 | 排版质量提升 80% |
| P0-2 | article-tools 自动化集成（封面 + 排版） | 大 | 减少 7 步手动操作 |
| P0-3 | 结构化 Prompt 工程 | 中 | 内容质量提升 |
| P1-1 | 微信 API 链路校验层 | 小 | 减少发布失败率 |
| P1-2 | 订阅号配额管理 | 小 | 防止误操作浪费配额 |
| P1-3 | 发布 URL 回显 | 小 | 用户体验提升 |
| P1-4 | 配图占位符方案 | 中 | 解决插入错位问题 |
| P2-1 | SSE 实时推送 | 中 | 轮询延迟消除 |
| P2-2 | 配置体系重构 | 大 | 维护性提升 |

---

## 五、平台规则对照表

### 5.1 微信公众号草稿 API 约束

| 字段 | 约束 | 当前状态 |
|------|------|---------|
| `title` | ≤32 字符 | ❌ 无校验 |
| `author` | ≤16 字符 | ❌ 无校验 |
| `digest` | ≤128 字符 | ⚠️ 硬截断 120 字符 |
| `content` | ≤20,000 字符，≤1MB | ❌ 无校验 |
| `content` HTML | 仅允许特定标签，`<script>`/`<style>` 等被过滤 | ❌ 正则替换可能产生禁止标签 |
| 图片 | 所有 `<img src>` 必须是微信 CDN URL | ✅ 已实现 |
| 封面图 | 必须是永久素材 media_id | ⚠️ 程序化棋盘格兜底丑 |
| 图片上传 | 临时素材接口有有效期，永久素材推荐 | ✅ 已实现 |

### 5.2 群发配额

| 账号类型 | 配额 | 当前状态 |
|---------|------|---------|
| 订阅号（未认证） | 无 API 发布权限（2025.7 起） | ❌ 无检测 |
| 订阅号（认证） | 4 次/月 | ⚠️ 仅对话框提示，无实际追踪 |
| 服务号（认证） | 无限制 | ⚠️ 无区分 |

---

## 六、结论

AI 创作模块的当前实现是一个**功能可用但体验断层的半成品**。核心问题不是"没有实现某个功能"，而是：

1. **最后一公里未自动化** — article-tools 作为关键排版工具完全游离在流程之外
2. **排版质量根本不够** — 正则替换方案无法处理微信公众号所需的复杂 Markdown 语法
3. **LLM 输出质量缺乏约束** — 没有针对微信公众号的平台化 prompt 工程

**最优先的两件事：**
- 引入 baoyu-markdown-to-html 作为 Markdown → 微信 HTML 的渲染引擎
- 将 article-tools（封面 + 排版）自动化集成到 AI 创作流程，作为推送前的必经环节

这两件事能解决 80% 的"排版丑、内容差"问题。后续再逐步完善 Prompt 工程、校验层、配额管理等。

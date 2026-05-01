# 微信公众号 Markdown 排版增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 充分利用 md2wechat-skill 的专业排版能力（主题/配色/AI 封面/布局模块），在 AI 创作流程中实现微信公众号专业级排版，保持优雅回退。

**Architecture:** 在现有 `wechat_publisher.py` 基础上扩展 baoyu 渲染器参数和配置项，增加 `WechatArticleRenderResult` 新字段打通 AI 封面路径，更新 md2wechat-skill 的 CLI 参数支持。

**Tech Stack:** Python (wechat_publisher.py), TypeScript (baoyu main.ts), Pygments (Phase 3 代码高亮)

---

## 文件变更总览

| 文件 | 操作 |
|------|------|
| `monitor/wechat_publisher.py` | 修改 |
| `config/settings.py` | 修改 |
| `scripts/article_generator.py` | 修改 |
| `frontend-vue/src/views/settings/WechatPublishSettings.vue` | 修改 |
| `~/.agents/skills/baoyu-markdown-to-html/scripts/main.ts` | 修改 |
| `tests/test_wechat_publisher_baoyu_integration.py` | 新建 |

---

### Task 1: 扩展 baoyu 脚本 CLI 参数

**文件:**
- Modify: `~/.agents/skills/baoyu-markdown-to-html/scripts/main.ts:257-313`

- [ ] **Step 1: 阅读当前 main.ts 的 CLI 解析逻辑**

在 `main()` 函数中找到参数解析循环（`for (let i = 0; i < args.length; i++)`），确认当前支持的参数。

- [ ] **Step 2: 添加 --ai-cover, --color, --layout-modules 参数解析**

在参数解析循环中添加：

```typescript
// 在 keepTitle 解析之后添加
let aiCover = false;
let color: string | undefined;
let layoutModules = false;

// 在 else if 分支中添加
} else if (arg === '--ai-cover') {
  aiCover = true;
} else if (arg === '--color' && args[i + 1]) {
  color = args[++i];
} else if (arg === '--layout-modules') {
  layoutModules = true;
```

- [ ] **Step 3: 将参数传递给 convertMarkdown**

修改 `convertMarkdown` 调用处，在 options 对象中添加：

```typescript
const result = await convertMarkdown(markdownPath, {
  title: title ?? undefined,
  theme: theme ?? 'default',
  keepTitle,
  aiCover,      // 新增
  color,        // 新增
  layoutModules, // 新增
});
```

- [ ] **Step 4: 修改 convertMarkdown 函数签名**

修改 `convertMarkdown` 函数接受新参数：

```typescript
export async function convertMarkdown(
  markdownPath: string,
  options?: {
    title?: string;
    theme?: string;
    keepTitle?: boolean;
    aiCover?: boolean;       // 新增
    color?: string;          // 新增
    layoutModules?: boolean; // 新增
  }
): Promise<ParsedResult>
```

- [ ] **Step 5: 在 convertMarkdown 内部使用 aiCover 和 color**

在 `convertMarkdown` 中，使用 `options?.color` 覆盖 `style.color`：

```typescript
// 在 style 构建处添加
if (options?.color) {
  style.color = options.color;
}
```

关于 `--ai-cover` 和 `--layout-modules`：
- 目前 `convertMarkdown` 不直接生成封面，需要在 `main()` 中根据 `aiCover` 标志额外调用封面生成逻辑（如果 md2wechat 有 `generateCover` 函数的话）
- `--layout-modules` 对应 `:::block` 语法支持——当前 baoyu 渲染器默认已解析，可通过 `layoutModules` 标志控制是否输出模块使用统计

先让 `--color` 和 `--layout-modules` 生效，`--ai-cover` 留 Phase 1 后续处理。

- [ ] **Step 6: 更新 stdout JSON 输出**

在返回对象中添加新字段：

```typescript
return {
  title,
  author,
  summary,
  htmlPath: finalHtmlPath,
  backupPath,
  contentImages,
  colorUsed: color,       // 新增
  layoutModulesUsed: layoutModules ? contentImages.length : 0, // 新增
};
```

- [ ] **Step 7: 测试 baoyu 脚本**

```bash
cd ~/.agents/skills/baoyu-markdown-to-html
bun scripts/main.ts test.md --theme dan-koe --color blue --layout-modules
```
验证 stdout 输出包含 `colorUsed` 和 `layoutModulesUsed` 字段。

- [ ] **Step 8: Commit**

```bash
git add scripts/main.ts
git commit -m "feat: add --ai-cover, --color, --layout-modules CLI params"
```

---

### Task 2: 扩展 WechatArticleRenderResult dataclass

**文件:**
- Modify: `monitor/wechat_publisher.py:60-69`

- [ ] **Step 1: 添加新字段到 dataclass**

在 `WechatArticleRenderResult` dataclass 的 `warnings` 字段后添加：

```python
    cover_image_path: str | None = None
    layout_modules_used: int = 0
    reading_time_minutes: float | None = None
```

- [ ] **Step 2: 写失败测试**

新建 `tests/test_wechat_publisher_baoyu_integration.py`:

```python
def test_render_result_has_new_fields():
    from monitor.wechat_publisher import WechatArticleRenderResult

    result = WechatArticleRenderResult(
        title="Test",
        content="<p>Test</p>",
        renderer="baoyu-markdown-to-html",
    )
    assert hasattr(result, "cover_image_path")
    assert result.cover_image_path is None
    assert hasattr(result, "layout_modules_used")
    assert result.layout_modules_used == 0
    assert hasattr(result, "reading_time_minutes")
    assert result.reading_time_minutes is None
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/test_wechat_publisher_baoyu_integration.py::test_render_result_has_new_fields -v
```
预期: PASS

- [ ] **Step 4: Commit**

```bash
git add monitor/wechat_publisher.py tests/test_wechat_publisher_baoyu_integration.py
git commit -m "feat: add cover_image_path, layout_modules_used, reading_time_minutes to WechatArticleRenderResult"
```

---

### Task 3: 扩展 _render_with_baoyu() 函数签名和调用逻辑

**文件:**
- Modify: `monitor/wechat_publisher.py:1033-1084`

- [ ] **Step 1: 扩展函数签名**

修改 `_render_with_baoyu()` 函数签名，在 `timeout_seconds` 参数后添加：

```python
    enable_ai_cover: bool = False,
    enable_layout_modules: bool = False,
```

- [ ] **Step 2: 在 command 构建中添加新参数**

在当前 command 构建后（color 处理之后）添加：

```python
    if enable_layout_modules:
        command.append("--layout-modules")
    if enable_ai_cover:
        command.append("--ai-cover")
```

- [ ] **Step 3: 从 payload 解析新字段并填充 dataclass**

在 `return WechatArticleRenderResult(...)` 调用中，从 payload 解析新字段：

```python
    return WechatArticleRenderResult(
        title=str(payload.get("title") or title or path.stem).strip(),
        author=str(payload.get("author") or "").strip() or None,
        digest=str(payload.get("summary") or "").strip() or None,
        content=content,
        html_path=str(html_path),
        renderer="baoyu-markdown-to-html",
        cover_image_path=str(payload.get("coverImagePath") or "").strip() or None,
        layout_modules_used=int(payload.get("layoutModulesUsed") or 0),
        reading_time_minutes=float(payload.get("readingTimeMinutes")) if payload.get("readingTimeMinutes") else None,
    )
```

- [ ] **Step 4: 更新 render_md_to_html_for_wechat() 传递参数**

修改 `render_md_to_html_for_wechat()` 函数签名添加：

```python
    enable_ai_cover: bool = False,
    enable_layout_modules: bool = False,
```

并传递到 `_render_with_baoyu()` 调用中。

- [ ] **Step 5: 运行测试验证**

```bash
pytest tests/test_wechat_publisher_baoyu_integration.py -v
```

- [ ] **Step 6: Commit**

```bash
git add monitor/wechat_publisher.py
git commit -m "feat: extend _render_with_baoyu to support --ai-cover and --layout-modules"
```

---

### Task 4: 打通 AI 封面到 save_to_draft 调用链

**文件:**
- Modify: `monitor/wechat_publisher.py:533-567` (save_to_draft 方法)
- Modify: `scripts/article_generator.py:1259-1286` (article_generator 中的调用)

- [ ] **Step 1: 确认 render_result.cover_image_path 可用**

确认 Task 3 已完成后，`render_md_to_html_for_wechat()` 返回的 `WechatArticleRenderResult` 包含 `cover_image_path`。

- [ ] **Step 2: 在 article_generator.py 中传递 cover_image**

在 `render_md_to_html_for_wechat()` 调用后，修改 `publisher.save_to_draft()` 调用：

当前代码:
```python
wx_result = publisher.save_to_draft(
    title=render_result.title,
    content=render_result.content,
    author=author_for_wx,
    digest=render_result.digest,
    ...
)
```

改为：
```python
# AI 封面优先于显式封面
effective_cover = (
    render_result.cover_image_path
    or str(self.cfg.get("wechat_cover_image") or "").strip()
    or None
)
wx_result = publisher.save_to_draft(
    title=render_result.title,
    content=render_result.content,
    author=author_for_wx,
    cover_image=effective_cover,  # 使用 AI 封面或配置封面
    digest=render_result.digest,
    ...
)
```

- [ ] **Step 3: Commit**

```bash
git add scripts/article_generator.py
git commit -m "feat: auto-use AI-generated cover from baoyu renderer"
```

---

### Task 5: 扩展配置项

**文件:**
- Modify: `config/settings.py:49-190`

- [ ] **Step 1: 在 settings.py 默认配置中添加新项**

在 `wechat_baoyu_markdown_to_html_script` 配置项附近添加：

```python
"wechat_baoyu_ai_cover": False,
"wechat_baoyu_layout_modules": False,
"wechat_baoyu_timeout": 120,
```

- [ ] **Step 2: 确认字段已有**

`wechat_default_theme` 和 `wechat_default_color` 已在 settings.py 中存在（line 173-174），无需重复添加。

- [ ] **Step 3: Commit**

```bash
git add config/settings.py
git commit -m "feat(config): add baoyu ai-cover, layout-modules, timeout settings"
```

---

### Task 6: article_generator 传递新 baoyu 参数

**文件:**
- Modify: `scripts/article_generator.py:1259-1265`

- [ ] **Step 1: 在 render_md_to_html_for_wechat 调用中添加新参数**

在调用 `render_md_to_html_for_wechat()` 时，从 cfg 中读取新配置：

```python
render_result = render_md_to_html_for_wechat(
    draft_path,
    theme=str(self.cfg.get("wechat_default_theme") or "default"),
    color=str(self.cfg.get("wechat_default_color") or "blue"),
    renderer=str(self.cfg.get("wechat_markdown_renderer") or "auto"),
    baoyu_script=str(self.cfg.get("wechat_baoyu_markdown_to_html_script") or ""),
    enable_ai_cover=bool(self.cfg.get("wechat_baoyu_ai_cover")),
    enable_layout_modules=bool(self.cfg.get("wechat_baoyu_layout_modules")),
)
```

- [ ] **Step 2: Commit**

```bash
git add scripts/article_generator.py
git commit -m "feat(articleGenerator): pass baoyu enable_ai_cover and enable_layout_modules"
```

---

### Task 7: 前端设置页面

**文件:**
- Modify: `frontend-vue/src/views/settings/WechatPublishSettings.vue`

- [ ] **Step 1: 添加主题列表常量**

在 `<script setup>` 中添加常用主题列表：

```typescript
const WECHAT_BAOYU_THEMES = [
  { label: '默认 (default)', value: 'default' },
  { label: '优雅 (grace)', value: 'grace' },
  { label: '简约 (simple)', value: 'simple' },
  { label: '淡雅 (dan-koe)', value: 'dan-koe' },
  { label: '极简 (minimal)', value: 'minimal' },
  { label: '科技 (tech)', value: 'tech' },
  { label: '温暖 (warm)', value: 'warm' },
  { label: '浆果 (berry)', value: 'berry' },
]
```

- [ ] **Step 2: 添加 AI 封面和布局模块开关**

在现有配置表单中添加：

```html
<NFormItem :label="t('settings.wechatBaoyuAiCover')">
  <NSwitch v-model:value="localConfig.wechat_baoyu_ai_cover" />
</NFormItem>

<NFormItem :label="t('settings.wechatBaoyuLayoutModules')">
  <NSwitch v-model:value="localConfig.wechat_baoyu_layout_modules" />
</NFormItem>
```

- [ ] **Step 3: 更新本地化文案**

在 `zh.json` 和 `en.json` 中添加：

```json
"wechatBaoyuAiCover": "AI 生成封面",
"wechatBaoyuLayoutModules": "启用布局模块",
```

- [ ] **Step 4: 确认主题/配色下拉框**

检查现有 `WechatPublishSettings.vue` 是否已有主题和配色选择器，如果有则增强选项，如果没有则添加。

- [ ] **Step 5: 构建验证**

```bash
cd frontend-vue && pnpm build 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add frontend-vue/src/views/settings/WechatPublishSettings.vue frontend-vue/src/locales/zh.json frontend-vue/src/locales/en.json
git commit -m "feat(settings): add baoyu AI cover and layout modules toggles"
```

---

### Task 8: Phase 3 — 本地渲染器代码高亮

**文件:**
- Modify: `monitor/wechat_publisher.py` (在 `_render_local_markdown` 函数内)

- [ ] **Step 1: 检查 Pygments 可用性**

```python
try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, TextLexer
    from pygments.formatters import HtmlFormatter
    _HAS_PYGMENTS = True
except ImportError:
    _HAS_PYGMENTS = False
```

- [ ] **Step 2: 修改代码块渲染逻辑**

在 `_render_local_markdown` 中，代码块渲染处（line 856-866）改为：

```python
if _HAS_PYGMENTS:
    try:
        lexer = get_lexer_by_name(code_lang) if code_lang else TextLexer()
        formatter = HtmlFormatter(nowrap=True, cssclass="codehilite")
        code_html = highlight("\n".join(code_lines), lexer, formatter)
        # 包裹外层样式
        code_html = (
            f'<pre style="margin:16px 0;padding:12px;overflow:auto;'
            f'background:#f6f4ef;border-radius:6px;line-height:1.55;">'
            f'{code_html}</pre>'
        )
    except Exception:
        # 回退到简单转义
        code_html = html.escape("\n".join(code_lines))
        code_html = (
            f'<pre style="margin:16px 0;padding:12px;overflow:auto;'
            f'background:#f6f4ef;border-radius:6px;line-height:1.55;">'
            f'<code>{code_html}</code></pre>'
        )
else:
    code_html = html.escape("\n".join(code_lines))
    code_html = (
        f'<pre style="margin:16px 0;padding:12px;overflow:auto;'
        f'background:#f6f4ef;border-radius:6px;line-height:1.55;">'
        f'<code>{code_html}</code></pre>'
    )
```

- [ ] **Step 3: 写测试**

```python
def test_local_renderer_code_block():
    from monitor.wechat_publisher import _render_local_markdown
    from pathlib import Path

    md = "```python\nprint('hello')\n```"
    html = _render_local_renderer(md, Path("."))
    assert "<code" in html or "codehilite" in html
    assert "hello" in html
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_wechat_publisher_baoyu_integration.py -v
```

- [ ] **Step 5: Commit**

```bash
git add monitor/wechat_publisher.py tests/test_wechat_publisher_baoyu_integration.py
git commit -m "feat: add Pygments syntax highlighting to local renderer fallback"
```

---

## Spec 覆盖检查

| 设计文档章节 | 对应 Task |
|------------|----------|
| 3.1 扩展 baoyu 渲染器参数 | Task 1 + Task 3 |
| 3.2 新增配置项 | Task 5 + Task 6 |
| 3.3 渲染结果增强 | Task 2 + Task 3 |
| 3.4 调用链改动 | Task 4 + Task 6 |
| 4. 前端交互 | Task 7 |
| 5. 非功能性（优雅回退） | Task 3 回退逻辑已存在 |
| 6. 测试场景 | 各 Task 中的测试 |
| Phase 3 本地渲染器 | Task 8 |

**覆盖率: 100%** ✅

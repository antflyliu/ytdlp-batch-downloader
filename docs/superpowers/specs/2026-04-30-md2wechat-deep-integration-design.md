# 微信公众号 Markdown 排版增强：深度集成 md2wechat

## 1. 背景与目标

当前项目 (`wechat_publisher.py`) 已通过 subprocess 调用 `baoyu-markdown-to-html` 脚本进行 Markdown → 微信公众号 HTML 渲染，但仅使用了 `convertMarkdown` 的基础功能。

**目标**：充分利用 md2wechat-skill 的完整能力（40+ 主题、43 种布局模块、AI 封面生成），在 AI 创作流程中实现专业级微信公众号排版，同时保持优雅回退。

---

## 2. 当前架构

```
article_generator.py
  → scripts/article_generator.py (run_article_task)
      → monitor/wechat_publisher.py
          ├── _render_with_baoyu()      # 调用 baoyu 脚本（仅基础 convertMarkdown）
          ├── _render_local_markdown()  # 纯 Python 回退渲染器
          └── save_to_draft()            # 上传图片 + 创建草稿
```

**问题**：
- `render_md_to_html_for_wechat()` 仅传递 `--theme default`，主题硬编码
- 不支持布局模块（`:::block` 语法）
- AI 封面生成、图片下载等能力未利用
- baoyu 失败时回退到简陋的本地渲染器

---

## 3. 改进设计

### 3.1 扩展 baoyu 渲染器参数

当前 `_render_with_baoyu()` 调用：

```bash
bun main.ts input.md --theme default --title "标题"
```

改进后支持：

```bash
bun main.ts input.md \
  --theme dan-koe \
  --title "标题" \
  --color blue \
  --ai-cover          # 启用 AI 生成封面 \
  --layout-modules    # 启用布局模块解析
```

对应 Python 侧改动：

```python
def _render_with_baoyu(
    path: Path,
    *,
    title: str,
    theme: str,
    color: str | None = None,
    enable_ai_cover: bool = False,
    enable_layout_modules: bool = False,
    baoyu_script: str | Path | None = None,
    timeout_seconds: int = 120,
) -> WechatArticleRenderResult:
```

### 3.2 新增配置项

| 配置项 | 默认值 | 说明 |
|-------|--------|------|
| `wechat_baoyu_theme` | `"default"` | md2wechat 主题名称 |
| `wechat_baoyu_color` | `"blue"` | 配色方案 |
| `wechat_baoyu_ai_cover` | `false` | 是否启用 AI 生成封面 |
| `wechat_baoyu_layout_modules` | `false` | 是否启用布局模块 |
| `wechat_baoyu_script` | `~/.agents/skills/...` | baoyu 脚本路径 |
| `wechat_baoyu_timeout` | `120` | 渲染超时秒数 |

### 3.3 渲染结果增强

当前 `WechatArticleRenderResult` 返回字段：

```python
@dataclass
class WechatArticleRenderResult:
    title: str
    content: str        # HTML 正文
    renderer: str      # "baoyu-markdown-to-html" / "local"
    html_path: str     # 本地预览 HTML 路径
    author: str | None
    digest: str | None
    warnings: list[str]
```

新增：

```python
    cover_image_path: str | None  # AI 生成的封面本地路径（仅当 enable_ai_cover=True 时）
    layout_modules_used: int      # 实际使用的布局模块数量
    reading_time_minutes: float   # 预估阅读时间（分钟）
```

### 3.4 调用链改动

```
article_generator.py
  ↓ 传递配置中的 baoyu 参数
monitor/wechat_publisher.py
  ↓ render_md_to_html_for_wechat(..., theme, color, enable_ai_cover, enable_layout_modules)
  ↓ _render_with_baoyu(...)
      ↓ subprocess.run([bun, script, path, --theme X, --color Y, --ai-cover, --layout-modules])
          ↓ 解析 stdout JSON + 读取生成的 HTML
      ↓ 返回 WechatArticleRenderResult（含 AI 封面路径）
  ↓ save_to_draft(..., cover_image=result.cover_image_path)
      ↓ 自动使用 AI 封面作为 thumb_media_id
```

### 3.5 优雅回退

```
baoyu 渲染成功 → 直接使用结果
baoyu 渲染失败（非 --baoyu 强制模式）→ 回退到本地渲染器
baoyu 脚本不存在 → 回退到本地渲染器
本地渲染器渲染失败 → 返回错误
```

## 4. 前端交互

在 `WechatPublishSettings.vue` 增加：

| UI 控件 | 配置项 |
|---------|--------|
| 主题选择下拉框（预置常用主题列表） | `wechat_baoyu_theme` |
| 配色选择（预置配色列表） | `wechat_baoyu_color` |
| 开关：AI 生成封面 | `wechat_baoyu_ai_cover` |
| 开关：启用布局模块 | `wechat_baoyu_layout_modules` |

主题列表从 `md2wechat-skill` 的 `themes.ts` 中提取，初始支持：
`default, grace, simple, dan-koe, minimal, tech, warm, berry`（8 个常用主题）

## 5. 非功能性

- **回滚友好**：仅增加可选配置，现有行为完全不变
- **错误隔离**：baoyu 渲染失败不影响本地渲染器回退
- **日志追踪**：baoyu 调用输出到 stderr，记录 INFO 日志
- **性能**：渲染超时 120s，超时则回退本地渲染器
- **依赖**：复用现有 `baoyu-markdown-to-html` 脚本，无新依赖

## 6. 测试场景

| 场景 | 预期 |
|------|------|
| baoyu 可用 + 默认配置 | 使用 baoyu 渲染，主题 default |
| baoyu 可用 + 自定义主题 | 使用指定主题渲染 |
| baoyu 可用 + AI 封面 | 返回封面路径，草稿使用该封面 |
| baoyu 不可用 | 回退到本地渲染器，不报错 |
| baoyu 强制模式 + 失败 | 抛出明确错误 |
| 本地渲染器回退 | 生成基础 HTML，正常创建草稿 |

---

## 7. 实施计划

### Phase 1: 核心基础设施（最小可行）
1. 扩展 `_render_with_baoyu()` 支持 `--ai-cover` 参数
2. 解析 baoyu stdout 中的 `coverImagePath` 字段
3. 在 `WechatArticleRenderResult` 增加 `cover_image_path` 字段
4. 修改 `save_to_draft` 调用链传递封面路径
5. 扩展配置项（settings.py / AiSettings.vue）

### Phase 2: 主题与布局
6. 支持 `--theme` 和 `--color` 参数化
7. 支持 `--layout-modules` 开关
8. 前端主题/配色选择器

### Phase 3: 完善回退与错误处理
9. 增强本地渲染器的代码高亮（引入 Pygments）
10. 添加渲染质量警告（如"使用了本地回退，排版效果有限"）

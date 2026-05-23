# baoyu-markdown-to-html (Vendored)

This directory contains a vendored copy of [baoyu-markdown-to-html](https://github.com/baoyu-xyz/baoyu-markdown-to-html), used to render Markdown articles to WeChat-compatible HTML.

## Setup

After cloning the repository, run:

```bash
cd scripts/markdown-to-html/md
bun install
```

This installs the npm dependencies (marked, front-matter, highlight.js, juice, etc.) required by the skill.

## Usage

This skill is called automatically by `monitor.wechat_publisher` when rendering markdown to HTML for WeChat publishing. No manual invocation is needed.

## Override

To use a different version, set one of:
- Environment variable: `BAOYU_MARKDOWN_TO_HTML_SCRIPT=/path/to/main.ts`
- Config key: `wechat_baoyu_markdown_to_html_script` in settings
- Function param: `baoyu_script` in `render_md_to_html_for_wechat()`

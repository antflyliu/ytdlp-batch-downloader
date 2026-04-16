# 任务计划：autoclip 集成可行性分析

## 目标
分析 autoclip 开源项目与当前 ytdlp-batch-downloader 的集成可行性，评估哪些特性可以借鉴/复用。

## 当前阶段
**Phase 1: 进行中**

---

## Phase 1: 项目研究（autoclip）
- [x] 1.1 获取 autoclip README 和项目介绍
- [x] 1.2 分析技术栈（FastAPI/Celery/React）
- [x] 1.3 分析 AI 处理 Pipeline（6步流程）
- [x] 1.4 分析依赖库（yt-dlp/whisper/prompt 工程）
- [x] 1.5 分析架构设计（前后端分离/异步任务）
- [x] 1.6 与当前项目特性对比
- [x] 1.7 输出集成可行性报告
- **Status:** ✅ complete

## Phase 2: 集成方案设计
- [x] 2.1 评估可复用模块（下载/字幕/Pipeline）— 见 findings.md
- [x] 2.2 评估架构改造成本 — 见 findings.md
- [x] 2.3 设计集成路径（轻量 vs 完整）— 见 findings.md
- [x] 2.4 制定实施计划
- **Status:** ✅ complete（2.1-2.4 全部完成）

## Phase 3: 决策与路线图
- [x] 3.1 向用户呈现分析结论
- [x] 3.2 确定是否实施集成
- [x] 3.3 制定实施路线图
- **Status:** ✅ complete

## Phase 4: 实施 — Stage 1 核心脚本
- [x] 4.1 `scripts/llm_client.py` — 多后端 LLM（qwen/openai/ollama/groq）
- [x] 4.2 `scripts/text_processor.py` — SRT 解析 + 分块
- [x] 4.3 `scripts/video_processor.py` — ffmpeg 切割 + 合集拼接
- [x] 4.4 `scripts/clip_pipeline.py` — 6 步 Pipeline 编排器
- [x] 4.5 `scripts/video_clipper.py` — CLI 入口
- [x] 4.6 `scripts/prompts/` — 5 个 Prompt 模板（outline/timeline/scoring/title/clustering）
- [x] 4.7 单元测试（39 个用例，pytest 全部通过）
- **Status:** ✅ complete（Stage 1 全部完成）

## Phase 4: 实施 — Stage 2 GUI 集成
- [x] 2.1 `config/settings.py` — 添加 llm_provider/api_key/model/base_url/min_score/category 配置字段
- [x] 2.2 `server/__main__.py` — `_api_config_save()` 白名单添加 LLM 配置字段
- [x] 2.3 `monitor_web/templates/modals/modal-config.html` — 新增「AI 视频切片」设置区块
- [x] 2.4 `monitor_web/js/modules/config.js` — 添加 LLM 配置 UI 绑定（加载/保存）
- [x] 2.5 `ytdownload_ui.py` — 新增「AI 视频切片」Tkinter UI 区块（提供商/评分/分类）
- [x] 2.6 语法验证（py_compile）+ 测试套件通过
- **Status:** ✅ complete（Stage 2 全部完成）

## Phase 5: 实施 — Stage 3 高级功能
- [ ] 3.1 B 站自动上传
- [ ] 3.2 自动切片触发（监控触发）
- [ ] 3.3 切片结果通知推送
- **Status:** 未开始

---

## 关键决策记录
| 日期 | 决策 | 理由 |
|------|------|------|
| 2026-04-17 | **采用轻量集成方案** | 不改变现有架构，仅新增 AI Pipeline 脚本 |
| 2026-04-17 | **LLM 优先通义千问** | 国内用户，费用低；设计为可插拔多后端 |
| 2026-04-17 | **分阶段迭代** | Stage 1 核心脚本 → Stage 2 GUI集成 → Stage 3 高级功能 |
| 2026-04-17 | **当前仅入 roadmap** | 暂不实施，后续迭代开发 |

## 5-Question Reboot Check
| 问题 | 答案 |
|------|------|
| Where am I? | Phase 1 项目研究中，正在汇总 findings |
| Where am I going? | Phase 1 完成后进入集成方案设计 |
| What's the goal? | 判断 autoclip 的 AI 切片功能是否/如何集成到当前项目 |
| What have I learned? | autoclip 使用 FastAPI+Celery+React 的现代化架构，AI Pipeline 有 6 步精细流程 |
| What have I done? | 获取 README、pipeline 代码、依赖列表 |

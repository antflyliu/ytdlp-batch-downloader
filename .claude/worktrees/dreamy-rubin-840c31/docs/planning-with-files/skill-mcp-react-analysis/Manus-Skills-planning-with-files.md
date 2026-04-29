# Manus Skills：planning-with-files 实践指南

> 基于 Claude Skills、MCP、ReAct 的工程化实践

---

## 引言

在 AI Agent 开发中，如何高效地组织任务、管理上下文、实现可靠的推理循环是核心挑战。本文从 Claude 官方博客和行业分析中提取核心观点，阐述 **Agent-ReAct-Skills-MCP-Tool** 的关系模型，并展示如何使用 **planning-with-files** 实践 ReAct 模式。

---

## 一、核心概念解析

### 1.1 Skills：任务特定的专业知识模块

**定义**（来源：Claude Blog, IntuitionLabs）：

> Claude Skills are folders containing a SKILL.md text file (with YAML frontmatter metadata) plus any associated scripts, documents, or assets. Each Skill "packages" a specific workflow or organizational guideline.

Claude Skills 是 Anthropic 于 2025 年 10 月推出的任务特定模块，本质上是包含 SKILL.md 文件和可选代码/资源的文件夹。当用户请求匹配 Skill 的条件时，Claude 自动加载该 Skill 的指令。

**核心特性**：

| 特性 | 说明 |
|------|------|
| **渐进式加载** | 元数据先加载（~100 tokens），完整指令按需加载（5k tokens） |
| **可执行** | 可包含 Python 等脚本执行确定性操作 |
| **可移植** | 跨 Claude.ai、Claude Code、Claude Agent SDK、API 使用 |

**使用场景**：
- 组织工作流：品牌指南、合规流程、文档模板
- 领域专业：Excel 公式、PDF 处理、数据分析
- 个人偏好：笔记系统、编码模式、研究方法

### 1.2 MCP：模型上下文协议

**定义**（来源：Claude Blog, IntuitionLabs）：

> Model Context Protocol (MCP) – an open standard introduced by Anthropic in late 2024 and donated to the Linux Foundation's Agentic AI Foundation (AAIF) in December 2025 – is a way of connecting an LLM like Claude to external tools and data sources in a uniform way.

MCP 是 Anthropic 于 2024 年 11 月推出的开放标准，2025 年 12 月捐赠给 Linux 基金会的 Agentic AI Foundation。截至 2026 年初，MCP 已成为最快采用的开源 AI 项目之一：

| 指标 | 数据 |
|------|------|
| 每月 SDK 下载 | 9700 万+ |
| 活跃服务器 | 10000+ |

**核心功能**：
- 标准化 LLM 与外部系统（GitHub、数据库、SaaS 平台、自定义 API）的连接
- 客户端-服务器架构，支持工具调用

### 1.3 Skills vs MCP：职责分离

**核心观点**（来源：Claude Blog）：

> MCP connects Claude to third-party tools, and skills teach Claude how to use them well.

| 层次 | 职责 | 示例 |
|------|------|------|
| **MCP** | 连接性 | 访问 Notion、GitHub、数据库 |
| **Skills** | 专业性 | 哪些页面要拉取、如何格式化输出、团队标准 |

**关键原则**：
- MCP 指令保持通用（如何正确使用服务器和工具）
- Skills 指令处理特定流程（何时查询、什么顺序、如何呈现）

---

## 二、Agent-ReAct-Skills-MCP-Tool 关系模型

### 2.1 层次结构

```
┌─────────────────────────────────────────────────────────┐
│                    Agent (智能体)                        │
│  ┌───────────────────────────────────────────────────┐  │
│  │              ReAct (推理-行动循环)                  │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────────┐       │  │
│  │  │ Thought │→ │ Action  │→ │ Observation │       │  │
│  │  └─────────┘  └─────────┘  └─────────────┘       │  │
│  │                    ↑                              │  │
│  │                    └────────── Loop ─────────────┘│  │
│  └───────────────────────────────────────────────────┘  │
│                         │                               │
│  ┌──────────────────────┼──────────────────────────┐   │
│  │         Skills (技能) │ 专业知识与工作流           │   │
│  │  ┌─────────────────┐ │ ┌─────────────────────┐  │   │
│  │  │ SKILL.md        │ │ │ 可选代码/脚本        │  │   │
│  │  │ (指令定义)       │ │ │ (执行能力)           │  │   │
│  │  └─────────────────┘ │ └─────────────────────┘  │   │
│  └──────────────────────┼──────────────────────────┘   │
│                         │                               │
│  ┌──────────────────────┼──────────────────────────┐   │
│  │    MCP (模型上下文协议) │ 外部系统连接              │   │
│  │  ┌────────┐  ┌──────┐ │ ┌─────────────────────┐  │   │
│  │  │ Client │  │Server│ │ │ (GitHub/DB/SaaS)    │  │   │
│  │  └────────┘  └──────┘ │ └─────────────────────┘  │   │
│  └──────────────────────┼──────────────────────────┘   │
│                         │                               │
│  ┌──────────────────────┴──────────────────────────┐   │
│  │              Tools (工具)                         │   │
│  │    MCP 工具 + 内置工具 (Bash/Read/Edit/Write)     │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 关系说明

| 组件 | 角色 | 决策点 |
|------|------|--------|
| **Agent** | 整体智能体，协调各组件 | 目标设定、任务分解 |
| **ReAct** | 推理框架 | 何时思考、何时行动 |
| **Skills** | 专业知识 | 如何做（流程） |
| **MCP** | 连接能力 | 访问什么（工具） |
| **Tools** | 执行能力 | 实际做什么 |

### 2.3 数据流

```
用户请求 → Agent 解析
           ↓
        ReAct: Thought (读取 task_plan.md)
           ↓
        ReAct: Action (调用 Skill + Tool)
           ↓
        Skill 加载指令 (渐进式)
           ↓
        MCP 调用外部工具
           ↓
        Tool 执行操作
           ↓
        ReAct: Observation (更新 progress.md)
           ↓
        ReAct: Loop (继续或结束)
```

---

## 三、planning-with-files 实践 ReAct

### 3.1 什么是 planning-with-files

**定义**：Manus 风格的文件规划模式，使用持久化的 Markdown 文件作为"磁盘上的工作内存"。

**文件结构**：

```
项目根目录/
├── docs/
│   ├── task-name/
│   │   ├── task_plan.md    ← 任务计划（阶段、进度）
│   │   ├── findings.md     ← 研究发现（知识沉淀）
│   │   └── progress.md     ← 会话进度（实时日志）
```

### 3.2 ReAct 循环在 planning-with-files 中的实现

| ReAct 阶段 | planning-with-files 实现 |
|------------|-------------------------|
| **Thought** | 读取 `task_plan.md` 了解当前阶段和目标 |
| **Action** | 执行工具调用，更新 `findings.md` 和 `progress.md` |
| **Observation** | 检查文件内容，确认进展 |
| **Loop** | 根据 `task_plan.md` 状态继续下一个阶段 |

### 3.3 实践示例

**场景**：撰写一篇技术文章

**Phase 1: Thought（思考）**
```bash
# 读取任务计划
cat docs/skill-mcp-react-analysis/task_plan.md

# 输出：
# ## 阶段
# ### Phase 1: 研究参考文章
# - [ ] 1.1 阅读参考文章
# ### Phase 2: 撰写文章
# - [ ] 2.1 整理核心观点
```

**Phase 2: Action（行动）**
```bash
# 执行研究，读取参考文章
curl -sSL "https://claude.com/blog/skills-explained" | ...

# 将研究发现写入 findings.md
cat >> docs/skill-mcp-react-analysis/findings.md << 'EOF'
## 1.1 Claude Blog: Skills Explained
- 核心观点: Skills 使用渐进式加载机制
- 验证结果: ✅ 官方确认
EOF

# 更新进度到 progress.md
cat >> docs/skill-mcp-react-analysis/progress.md << 'EOF'
### 2026-04-15 16:30
- [x] 完成 Phase 1 研究
- 开始 Phase 2 撰写
```

**Phase 3: Observation（观察）**
```bash
# 检查进度
cat docs/skill-mcp-react-analysis/progress.md

# 检查任务状态
grep -E "^\- \[x\]" docs/skill-mcp-react-analysis/task_plan.md | wc -l
```

**Phase 4: Loop（循环）**
- 如果还有未完成任务 → 返回 Thought
- 如果任务完成 → 标记完成状态

### 3.4 关键规则

| 规则 | 说明 |
|------|------|
| **2-Action 规则** | 每 2 次视图/搜索操作后，立即保存关键发现到文件 |
| **读后再决定** | 重大决策前先读取计划文件 |
| **行动后更新** | 完成任何阶段后更新 task_plan.md 状态 |
| **记录所有错误** | 每个错误写入 progress.md |

---

## 四、工程化落地建议

### 4.1 Skills 编写规范

```yaml
---
name: planning-with-files
description: 使用持久化 Markdown 文件规划任务
user-invocable: true
allowed-tools: "Read, Write, Edit, Bash, Glob, Grep"
hooks:
  UserPromptSubmit:
    - hooks:
        - type: command
          command: |
            PLAN=$(find docs -name task_plan.md 2>/dev/null | head -1)
            if [ -n "$PLAN" ]; then
              echo "[planning-with-files] ACTIVE PLAN: $PLAN"
              head -30 "$PLAN"
            fi
---
```

**最佳实践**：
- 使用 YAML frontmatter 定义元数据
- 指令简洁明确，包含具体示例
- 支持渐进式加载，避免一次性加载所有内容

### 4.2 MCP 集成策略

| 场景 | 策略 |
|------|------|
| 官方 MCP 服务器 | 直接使用，保持指令通用 |
| 自定义 MCP | 指令保持通用，Skills 处理特定流程 |
| 多 MCP 协调 | 使用 Skills 定义调用顺序 |

### 4.3 ReAct 实现模式

```python
# 伪代码：ReAct 循环实现
async def react_loop(task: str, plan_file: str):
    while True:
        # Thought: 读取计划
        plan = await read_file(plan_file)
        current_phase = get_current_phase(plan)
        
        # Action: 执行任务
        result = await execute_phase(current_phase)
        
        # Observation: 更新状态
        await update_progress(plan_file, current_phase, result)
        
        # Loop: 检查是否完成
        if is_complete(plan):
            break
        
        await sleep(0.1)  # 避免过度循环
```

### 4.4 完整工作流

```
1. 任务启动
   ↓
2. 创建 docs/{task}/ 目录结构
   ↓
3. 初始化 task_plan.md（阶段规划）
   ↓
4. ReAct 循环开始
   ├─ Thought: 读取当前阶段
   ├─ Action: 执行 + 写文件
   ├─ Observation: 检查结果
   └─ Loop: 继续或结束
   ↓
5. 任务完成，输出产物
```

---

## 五、总结

### 核心观点

1. **Skills vs MCP**：MCP 负责"连接什么"（工具访问），Skills 负责"如何做"（工作流逻辑）
2. **ReAct 框架**：思考-行动-观察-循环的推理模式，是 Agent 的核心
3. **planning-with-files**：通过文件系统实现持久化上下文，解决 LLM 上下文窗口限制

### 实践要点

| 要点 | 说明 |
|------|------|
| **职责分离** | MCP 处理连接，Skills 处理流程，ReAct 处理协调 |
| **渐进加载** | 使用 Skills 的渐进式披露机制优化 token 使用 |
| **持久化** | 关键信息写入文件，避免丢失在上下文窗口中 |
| **状态跟踪** | 使用 task_plan.md 管理任务阶段，progress.md 记录实时进度 |

### 进一步阅读

- [Skills explained: How Skills compares to prompts, Projects, MCP, and subagents](https://claude.com/blog/skills-explained)
- [Extending Claude's capabilities with skills and MCP servers](https://claude.com/blog/extending-claude-capabilities-with-skills-mcp-servers)
- [Claude Skills vs. MCP: A Technical Comparison for AI Workflows](https://intuitionlabs.ai/articles/claude-skills-vs-mcp)

---

*本文基于 Claude 官方博客和 IntuitionLabs 分析撰写，观点已联网验证。*

# 研究发现

## Phase 1: 参考文章阅读

### 1.1 Claude Blog: Skills Explained
- **核心观点**: Skills 是包含指令、脚本和资源的文件夹，Claude 动态发现和加载。Skills 使用渐进式披露：元数据先加载（~100 tokens），完整指令按需加载（5k tokens）。
- **原文摘要**: Skills 是任务特定的模块，本质上是带有 SKILL.md 和可选代码/资源的文件夹。当用户请求匹配 Skill 的条件时，Claude 自动加载该 Skill 的指令。
- **验证结果**: ✅ 官方文档确认，Skills 通过 progressive disclosure 实现高效 token 使用

### 1.2 Claude Blog: Extending Claude Capabilities
- **核心观点**: MCP 连接 Claude 到第三方工具，Skills 教 Claude 如何很好地使用它们。MCP 负责连接性，Skills 负责专业性。
- **原文摘要**: MCP 就像进入商店的通道，Skills 就像店员的 expertise。MCP 服务器给 Claude 访问外部系统的能力，Skills 提供使用这些连接的上下文。
- **验证结果**: ✅ 官方确认，MCP 负责连接，Skills 负责工作流逻辑

### 1.3 IntuitionLabs: Claude Skills vs MCP
- **核心观点**: Skills 是任务特定模块，编码可重复的流程和专业技能。MCP 是连接 LLM 到外部工具和数据源的开放标准。截至 2026 年初，MCP 已成为最快采用的开源 AI 项目之一，每月 SDK 下载超过 9700 万次，有 10000+ 活跃服务器。
- **原文摘要**: Claude Skills (2025年10月) 让用户将程序性知识和首选工作流编码为可重用的"技能"。MCP (2024年11月) 是连接任何 LLM 到外部系统（数据库、SaaS 工具、自定义 API）的协议。
- **验证结果**: ✅ 数据来自官方统计，MCP 生态快速增长

### 1.4-1.6 其他参考文章
- dev.to 和 block.github.io 文章无法访问（404/超时），但已有足够核心内容

## Phase 2: 观点整合

### Agent-ReAct-Skills-MCP-Tool 关系模型

**层次结构**:
```
Agent (智能体)
  ├── ReAct (推理-行动模式)
  │   ├── Thought (思考)
  │   ├── Action (行动)
  │   ├── Observation (观察)
  │   └── Loop (循环)
  ├── Skills (技能)
  │   ├── SKILL.md (指令定义)
  │   ├── 可选代码/脚本
  │   └── 渐进式加载机制
  ├── MCP (模型上下文协议)
  │   ├── 客户端 (Claude)
  │   ├── 服务器 (外部工具)
  │   └── 标准化协议
  └── Tools (工具)
      ├── MCP 工具
      └── 内置工具
```

**关系**:
- **MCP**: 提供外部系统连接（工具访问能力）
- **Skills**: 提供使用工具的专业知识（工作流逻辑）
- **ReAct**: 推理框架，决定何时/如何调用 Skills 和 Tools
- **Tools**: 实际执行的操作（由 MCP 暴露）

### planning-with-files 实践 ReAct

**ReAct 循环**:
1. **Thought** → 分析任务，读取 task_plan.md 了解当前阶段
2. **Action** → 执行工具调用（读取、搜索、编写）
3. **Observation** → 观察结果，更新 progress.md
4. **Loop** → 重复直到任务完成

**planning-with-files 的 ReAct 实践**:
- **Thought**: 读取 task_plan.md 确定当前阶段和目标
- **Action**: 
  - 使用工具执行任务
  - 将研究发现写入 findings.md
  - 将进度写入 progress.md
- **Observation**: 检查文件内容，确认进展
- **Loop**: 根据 task_plan.md 状态继续下一个阶段

### 工程化落地建议

1. **Skills 编写规范**:
   - 使用 YAML frontmatter 定义元数据
   - 指令简洁明确，示例具体
   - 支持渐进式加载

2. **MCP 集成策略**:
   - 优先使用官方 MCP 服务器
   - 自定义 MCP 保持指令通用
   - Skills 处理工作流， MCP 处理连接

3. **ReAct 实现**:
   - 使用 planning-with-files 管理状态
   - 每个 Action 后更新 progress.md
   - 关键决策记录到 findings.md

4. **最佳实践**:
   - Skills 专注于"如何做"（流程）
   - MCP 专注于"连接什么"（工具）
   - ReAct 框架协调两者

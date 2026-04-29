# /ralph vs /ralplan 核心区别

> 整理自 oh-my-claudecode 技能注册表 (omc-reference) 与 CLAUDE.md 配置
> 创建时间：2026-04-11

---

## 快速对照

| 维度 | `/ralph` | `/ralplan` |
|------|----------|------------|
| **核心循环** | Do → Verify → Fix → Verify（直到 PASS） | Plan → Critique → Revise → Consensus |
| **触发点** | 执行过程中持续验证 | 执行前先达成共识 |
| **结束条件** | 验证通过（PASS） | 多方无异议（Consensus） |
| **类比** | 自动化 QA 巡检员 | 多方参与的架构评审会 |
| **适用场景** | bug fix、功能交付 | 重大决策、架构设计 |
| **驱动方式** | 执行驱动 | 规划驱动 |

---

## /ralph — 持久循环直到完成 + 验证

### 定位

执行驱动的**持续迭代** workflow。不达目的不罢休——持续执行、验证、修复循环。

### 核心行为

- 每轮结束后主动调用 verifier 确认结果
- 验证失败则自动进入下一轮修复，直到通过
- 支持与 team pipeline 组合（`team ralph`）
- 有明确的「完成标准」，通过验证来判定是否完成

### 典型场景

- **Bug 修复**：修 → 验 → 修 → 验，直到测试全绿
- **功能实现**：写 → 验 → 补，直到覆盖达标
- 有明确完成标准且需要多轮 self-correct 的任务

### 底层模型

```
doSomething()
  └─ verify() → FAIL? → doSomething() again
                └─ PASS? → done
```

### 组合用法

```
/team ralph   ← team pipeline + Ralph 风格顺序验证
```

---

## /ralplan — 共识规划 workflow

### 定位

规划驱动的**协调** workflow。生成计划后，主动征询多方意见，在实施前寻求共识。

### 核心行为

- 生成计划后，主动征询不同 agent 或 perspectives 的意见
- 在实施前寻求共识，挑战假设，识别盲点
- 可以调用 `critic` agent 对计划进行红队审查
- 输出是经过多方审视的、稳健的执行计划

### 典型场景

- **重大架构决策**：先多方辩论，再执行
- **多方依赖的复杂任务**：确保各方对齐
- 需要打破 echo chamber 的场景——让不同角色挑战计划

### 底层模型

```
proposePlan()
  └─ critique() → 识别问题 → revisePlan()
                  └─ 无异议? → done
```

---

## 一句话核心区别

> **`/ralph` 是做完再验，`/ralplan` 是做完规划再验。**

- `/ralph`：执行 → 验证失败 → 修复 → 验证 → ... → 通过为止
- `/ralplan`：规划 → 被挑战 → 修订 → 共识 → 执行

---

## CLAUDE.md 中的触发配置

```text
Keyword triggers:
  "ralph" → ralph          ← 触发持久循环
  "ralplan" → ralplan      ← 触发共识规划
```

两者都是 workflow skill，通过 `/oh-my-claudecode:ralph` 或 `/oh-my-claudecode:ralplan` 调用。

---

## 相关 Agent

| Agent | 角色 |
|-------|------|
| `verifier` (sonnet) | `/ralph` 的验证执行者 |
| `critic` (opus) | `/ralplan` 的计划挑战者 |
| `planner` (opus) | 两者都可能调用的规划生成器 |
| `executor` (sonnet) | `/ralph` 的修复执行者 |

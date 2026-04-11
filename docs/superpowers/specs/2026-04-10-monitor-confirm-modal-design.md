# 监控启动确认弹框与共享确认框升级 — 设计方案

> 日期：2026-04-10  
> 状态：已在对话中确认，待用户审阅书面 spec  
> 影响文件：`monitor_web/index.html`

## 1. 背景

当前“启动监控”入口在 `monitor_web/index.html:4490` 的 `toggleScheduler()` 中仍使用浏览器原生 `confirm()`（`monitor_web/index.html:4505`）。这会导致：

- 弹框视觉完全脱离当前 Web UI
- 无法遵循 `DESIGN.md` 的暖白 Claude 风格
- 交互语义不清晰：当前“确定/取消”实际表达的是“是否自动下载”，而不是“是否启动监控”

与此同时，项目已经存在共享应用内确认框：

- HTML：`monitor_web/index.html:3025` 的 `#modalAppConfirm`
- 样式：`monitor_web/index.html:1300` 附近
- 逻辑：`monitor_web/index.html:4196` 的 `showAppConfirm()`
- 已有调用点：`monitor_web/index.html:4539`、`4556`、`4578`、`6124`

因此本次不新建第二套弹框，而是在现有共享确认框基础上做最小、清晰、可复用的升级。

---

## 2. 目标与非目标

### 2.1 目标

1. 用应用内弹框替换“启动监控”场景下的原生 `confirm()`
2. 将共享确认框升级为更统一的 Claude/Anthropic 风格：暖白弹框 + 柔和暖调边框/阴影 + 更清晰的排版层级
3. 保留项目现有功能色语义：
   - 启动类主按钮保持绿色
   - 危险类主按钮保持红色
4. 让共享确认框支持“轻表单确认”：在确认框中增加一个可选 checkbox 区域
5. 保持已有调用点尽量少改或不改，避免为了一个 checkbox 重构整个 modal 系统

### 2.2 非目标

1. 不重做整个站点主题，不把所有 modal 全量改成 Claude 站点视觉
2. 不抽象成通用多字段表单构建器
3. 不修改“停止监控”现有语义
4. 不引入新的 JS 文件或拆分前端架构，本次改动集中在 `monitor_web/index.html`

---

## 3. 当前状态基线

### 3.1 启动监控的现状

当前未运行时，按钮由 `updateSchedulerUI()` 设置为：

- 文案：`▶ 启动监控`（`monitor_web/index.html:4320`）
- 点击：`toggleScheduler()`（`monitor_web/index.html:4322`）

进入启动分支后，代码用原生 `confirm()` 询问是否自动下载：

```js
const autoDl = confirm(
  "启动监控\n\n☑ 扫描到新视频后立即下载？\n\n" +
  "（勾选 → 每次扫描完成自动开始下载，\n" +
  "   最多 2 个视频同时下载）"
);
```

随后直接把 `auto_download: autoDl` 发给 `/scheduler/start`。

### 3.2 共享确认框的现状

共享确认框当前支持：

- 标题
- 正文 message
- 确认/取消按钮
- `danger` 变体
- 返回布尔值（确认/取消）

其现有使用方式适合“纯确认”场景，但不适合“确认前先设一个选项”的场景。

---

## 4. 设计结论

### 4.1 总体方案

采用**在现有共享 modal 基础上做轻增强**的方案：

- 继续复用 `#modalAppConfirm`
- 继续复用共享 open/close 行为与当前取消生命周期
- 扩展其内容区，使其既能承载普通确认，也能承载一个 checkbox 表单区
- 保持现有 `showAppConfirm()` 的布尔返回契约不变
- 在同一套 modal 之上新增 `showAppConfirmWithCheckbox()` 包装器，专门返回结构化结果
- 仅把“启动监控”这一处改为使用 checkbox 包装器
- 其他已有调用点继续走普通确认模式

这是本次最合适的平衡点：

- 比“新做一个专用启动弹框”更统一
- 比“抽象成完整表单框架”更轻量
- 与当前代码组织方式一致，便于维护

---

## 5. 视觉设计

### 5.1 视觉方向

采用“**暖白弹框 + 保留项目功能色**”的折中方案，遵循 `DESIGN.md` 的以下原则：

- 暖白/羊皮纸背景，而不是深色弹框
- 标题与正文形成更明显的阅读层级
- 以暖调 ring / 边框 / 阴影替代偏冷、偏硬的现有边界
- 保留功能色做主动作强调，而不是把所有按钮都统一成品牌色

### 5.2 具体表现

> 样式作用域要求：所有暖白化、暖灰按钮、标题/边框/阴影等视觉覆盖，必须严格限定在 `#modalAppConfirm` 下；不得改写共享 `.modal-*`、全局 `.btn-ghost` 或其他 modal 的通用样式，避免影响 `modalScanConfirm`、`modalAccount` 等现有弹框。

#### 弹框容器
- 背景：接近 `#f5f4ed` / `#faf9f5`
- 边框：暖米色边框
- 阴影：柔和暖调阴影 + 轻 ring
- 圆角：比当前 modal 略柔和，保持与 `DESIGN.md` 一致的舒适感

#### 标题区
- 标题层级更强，适合短句标题
- 标题颜色改为暖黑/暖深灰，而非冷白
- 关闭按钮改成更轻的暖灰小按钮，避免系统弹框感

#### 正文区
- 正文使用暖灰文字
- 行高提升到约 `1.6`
- 对辅助说明使用更浅一层的文字色，形成主次信息节奏

#### 按钮
- 主按钮支持三种 tone：
  - `primary`：默认主色（保留现有通用确认使用）
  - `success`：绿色，用于“启动监控”
  - `danger`：红色，用于删除/停止等高风险操作
- 次按钮改为暖灰次级按钮，不再使用偏冷的当前 ghost 视觉

#### danger 变体
- `danger` 变体继续保留
- 仅强化标题/边框/主按钮，不使用整块红底
- 保证高风险操作仍有明显辨识度，但不刺眼

---

## 6. 交互设计

### 6.1 启动监控场景的新交互

“启动监控”从原来的真假二选一确认，改为真正表单确认：

- 标题：`启动监控`
- 正文：简短说明“开始按计划扫描账号更新”
- Checkbox：`扫描到新视频后自动下载`
- Checkbox 辅助说明：`每轮扫描完成后自动开始下载，最多 2 个视频同时下载`
- 主按钮：`启动监控`
- 次按钮：`取消`

语义变更如下：

| 用户动作 | 结果 |
|---|---|
| 点击“启动监控”且勾选 checkbox | 启动监控，`auto_download = true` |
| 点击“启动监控”且未勾选 checkbox | 启动监控，`auto_download = false` |
| 点击“取消”/关闭弹框/按 Esc | 不启动 |

这能修复当前“取消其实也会继续执行另一种语义”的问题，使按钮含义与结果完全一致。

### 6.2 普通确认场景

已有场景（如动态代理调度启动/停止、删除提供方）保持：

- 仍展示标题 + 正文 + 主次按钮
- 不出现 checkbox 区域
- 仍然返回确认/取消结果
- 仅共享升级后的视觉样式

---

## 7. 组件边界与 API 设计

### 7.1 组件边界

本次只升级一个共享组件：`#modalAppConfirm`

它承担两类能力：

1. **普通确认模式**
2. **轻表单确认模式（当前只支持一个 checkbox）**

边界明确如下：

- 只处理“确认前设置一个简单选项”的需求
- 不负责多输入项表单
- 不承载复杂验证逻辑
- 不变成通用动态表单引擎

### 7.2 `showAppConfirm()` / `showAppConfirmWithCheckbox()` 扩展方向

推荐保留现有 `showAppConfirm()` 的布尔语义不变，并在同一套 `#modalAppConfirm` 之上新增一个轻量包装器 `showAppConfirmWithCheckbox()`，只给需要 checkbox 结果的调用点使用。

推荐的 options 结构：

```js
showAppConfirmWithCheckbox({
  title: '启动监控',
  message: '开始按计划扫描账号更新。',
  confirmText: '启动监控',
  cancelText: '取消',
  variant: 'default',
  confirmTone: 'success',
  checkbox: {
    label: '扫描到新视频后自动下载',
    description: '每轮扫描完成后自动开始下载，最多 2 个视频同时下载',
    checked: true,
  },
})
```

字段说明：

| 字段 | 用途 |
|---|---|
| `variant` | 控制整体 modal 风格，如 `danger` |
| `confirmTone` | 控制主按钮颜色，如 `primary` / `success` / `danger` |
| `checkbox` | 必填（仅此包装器）；显示 checkbox 区域 |

`showAppConfirm()` 继续给以下现有调用点使用：

- `monitor_web/index.html:4539`
- `monitor_web/index.html:4556`
- `monitor_web/index.html:4578`
- `monitor_web/index.html:6124`

### 7.3 返回值策略

为避免混合 boolean/object 返回导致误用，返回契约拆分如下：

- **`showAppConfirm()`**：继续返回 boolean
- **`showAppConfirmWithCheckbox()`**：返回结构化结果

建议结构如下：

```js
{
  confirmed: true,
  checked: true,
}
```

或：

```js
{
  confirmed: true,
  checked: false,
}
```

取消时：

```js
{
  confirmed: false,
}
```

说明：

- `checked` 仅在 `confirmed === true` 时有意义
- 这样可以避免“取消”与“确认但未勾选”在语义上混淆
- `toggleScheduler()` 使用结构化结果
- 其他现有调用点保持 boolean 协议，不需要跟着重写

---

## 8. DOM 与样式设计

### 8.1 HTML 扩展

在 `#modalAppConfirm` 的 body 中新增一个可切换显隐的轻表单区域，结构应尽量复用现有“立即扫描确认”弹框的 checkbox 表达方式（参考 `monitor_web/index.html:2997-3020` 与 `monitor_web/index.html:5121-5150`），包括：

- checkbox 容器
- checkbox label
- checkbox hint / description
- 与正文区之间清晰的分组间距

在未传 `checkbox` 配置时，该区域完全隐藏，不占布局空间。

### 8.2 布局节奏

目标布局顺序：

1. 标题区
2. 正文说明
3. checkbox 表单区（可选）
4. 底部按钮区

其中 checkbox 区域应采用清晰的块级视觉分组，避免看起来像正文的一部分。

### 8.3 可访问性与键盘行为

继续保留现有行为并补强：

- 若已有未完成的 app confirm，打开新的确认框时仍先以“取消”方式关闭前一个，保持当前 `monitor_web/index.html:4198-4202` 的生命周期语义
- `Esc` 关闭视为取消
- 点击遮罩视为取消
- 点击右上角关闭按钮视为取消
- 打开后默认聚焦主按钮
- checkbox 可被键盘聚焦和切换
- `focus-visible` 继续使用蓝色焦点环，延续当前项目可访问性约定

---

## 9. 启动监控的数据流

新的 `toggleScheduler()` 启动分支流程：

1. 检测当前不是运行中状态
2. 调用升级后的 `showAppConfirmWithCheckbox()`，以 checkbox 模式打开“启动监控”弹框
3. 若用户取消：
   - 直接恢复按钮状态
   - 不调用 `/scheduler/start`
4. 若用户确认：
   - 读取 checkbox 状态
   - 调用 `/scheduler/start`，请求体带上 `auto_download`
5. 成功后更新 UI 与 toast

这与当前后端契约兼容：后端仍只接收 `auto_download: true/false`，无需调整 API。

---

## 10. 兼容策略

### 10.1 保持不变的内容

以下调用点仍可以继续使用原有布尔语义：

- `monitor_web/index.html:4539` 停止动态代理调度
- `monitor_web/index.html:4556` 启动动态代理调度
- `monitor_web/index.html:4578` 立即刷新全部列表 API
- `monitor_web/index.html:6124` 删除提供方

### 10.2 需要改造的内容

仅以下场景需要切换到 checkbox 模式：

- `monitor_web/index.html:4505` 原生 `confirm()` → 应用内轻表单确认框

### 10.3 风险控制

- 不改 modal 打开/关闭基础机制
- 不改其他 modal 组件结构
- 不改 `/scheduler/start` API
- 改动范围集中，便于回滚

---

## 11. 测试与验收

### 11.1 功能验收

1. **启动监控 + 勾选自动下载**
   - 点击“启动监控”
   - 勾选 checkbox
   - 请求发出 `auto_download: true`
   - UI 正常切到运行中

2. **启动监控 + 不勾选自动下载**
   - 请求发出 `auto_download: false`
   - 其余行为正常

3. **取消启动**
   - 点击取消 / 遮罩 / Esc / 关闭按钮
   - 不调用 `/scheduler/start`
   - UI 不进入运行态

4. **危险确认场景**
   - 删除提供方等 danger 弹框仍正常工作
   - 按钮、标题、边框危险语义仍清晰

5. **普通确认场景**
   - 启动/停止动态代理调度等功能逻辑不变
   - 只是视觉升级

### 11.2 视觉验收

1. 弹框与当前深色背景存在明确层次反差
2. 暖白风格与 `DESIGN.md` 一致，不再像浏览器系统弹窗
3. 主按钮语义清晰：启动=绿色，危险=红色
4. checkbox 区域与正文区分明确，不混乱
5. 按钮文案与实际结果一致，不再误导

---

## 12. 回滚策略

如果升级后的共享确认框引入回归，可按最小范围回滚：

1. 保留共享确认框样式升级
2. 单独把 `toggleScheduler()` 切回原有逻辑（不推荐，但可快速止血）
3. 或直接回滚 `#modalAppConfirm` 与 `showAppConfirm()` 的相关 diff

由于变更只集中在 `monitor_web/index.html` 单文件，回滚成本较低。

---

## 13. 最终实施结论

本次采用以下实现方向：

- 升级现有共享确认框 `#modalAppConfirm`
- 视觉改为暖白 Claude 风格，但保留项目功能色语义
- 在共享确认框中加入单个 checkbox 的轻表单能力
- 把“启动监控”从原生 `confirm()` 改为真正的应用内表单确认
- 保持其他确认场景调用方式尽量不变

这是当前需求下复杂度最低、统一性最好、风险最可控的方案。

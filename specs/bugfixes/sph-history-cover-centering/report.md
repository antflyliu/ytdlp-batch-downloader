# Bugfix Report: sph-history-cover-centering

## Bug Name
`sph-history-cover-centering` — 视频号 SPH 解析历史页卡片中视频封面未垂直居中

## 严重程度
**LOW** — 纯 UI 样式问题,不影响功能正确性,但视觉上 cover 偏顶部,卡片下半部分留白不协调

## 现象 (Symptom)

「视频号 SPH → 解析历史」页中,每条历史卡片是横向布局:
- 左侧:视频封面(180px 宽, 16:9 固定比例)
- 右侧:作者 + 标题 + 描述 + 下载按钮 + 重新解析

实际显示:封面贴在卡片顶部,下方留出大块空白(约 100px),与右侧 meta 区域明显错位,看起来像 cover 没对齐。

## 根因 (Root Cause)

**位置:** `frontend-vue/src/views/Channels/ParseHistory.vue:352`

**问题 CSS:**
```css
.sph-history-card {
  display: flex;
  flex-direction: row;
  gap: 14px;
  align-items: stretch;   /* ← 罪魁 */
  border-left: 3px solid var(--accent);
}

.sph-history-card__cover {
  flex: 0 0 auto;
  width: 180px;
  aspect-ratio: 16 / 9;   /* ← 锁死 101.25px 高度,无法被 stretch 拉伸 */
  ...
}
```

**事实链:**

1. `flex-direction: row` → cross axis 是垂直方向
2. `align-items: stretch` → 期望子元素沿 cross axis 拉伸填满
3. 但 `.sph-history-card__cover` 设有 `aspect-ratio: 16/9` + `width: 180px` → 高度被锁定为 180 × 9/16 ≈ 101.25px,无法被拉伸
4. 右侧 `.sph-history-card__meta` 内容(标题 + 描述 + 3 个下载按钮 + 重新解析)实测约 180-220px 高
5. card 高度 = max(101.25, 200) = 200px
6. cover 留在顶部,下方约 100px 空白

`stretch` 试图拉但拉不动 → 元素默认保持其 intrinsic size 并 top-aligned。

## 修复 (Fix)

**位置:** `frontend-vue/src/views/Channels/ParseHistory.vue:352`

**修改前:**
```css
.sph-history-card {
  display: flex;
  flex-direction: row;
  gap: 14px;
  align-items: stretch;
  border-left: 3px solid var(--accent);
}
```

**修改后:**
```css
.sph-history-card {
  display: flex;
  flex-direction: row;
  gap: 14px;
  /* 2026-06-16 fix: align-items center 替代 stretch。
     cover 有 aspect-ratio: 16/9 无法被拉伸,stretch 时会停留在顶部留白约 100px。
     改为 center 后,cover 在 meta 比它高时垂直居中,meta 仍占满 (flex: 1 1 0) 不受影响。*/
  align-items: center;
  border-left: 3px solid var(--accent);
}
```

**为什么不用 `align-self: center` 加在 cover 上:**
- `align-items` 在父级声明影响全部子元素,语义更清晰
- meta 已是 `flex: 1 1 0`(占满剩余宽度),center 对它无视觉影响
- 一行改动 vs 两行,且父级声明表达"我希望这个 flex 容器垂直居中其子元素"的意图

**移动端断点(≤640px)的影响:**
该 CSS 段被 `flex-direction: column` 媒体查询覆盖,父级 cross axis 变为水平,`align-items: center` 此时仅让 meta 水平居中(实际是 100% 宽度无变化),cover 仍是 `width: 100%` 占满。布局不变。

## 回归测试 (Regression Test)

CSS 布局 bug 难以用单元测试覆盖,本 fix 的"测试"是:

1. **CSS 注释 + 根因记录**(本文件):详细记录 align-items 选择的依据与历史,避免后续开发者误改回 stretch
2. **手动视觉验证**:浏览器打开解析历史页,确认 cover 在卡片垂直方向居中,不再贴顶
3. **多 viewport 验证**:
   - 桌面 (>640px):cover 居中
   - 移动 (≤640px):cover 占满宽度 100%,flex-direction 变为 column 后仍正常堆叠

## 验证 (Verification)

- `npx vue-tsc --noEmit` → exit=0
- 视觉检查 ParseHistory 列表卡片(桌面 + 移动断点)

## 关联改动

此 fix 是 commit `397cf34` (feat(frontend-history)) 引入的视觉问题 — 当时只关注了内容布局(flex row + cover),未覆盖对齐细节。Cover + meta 高度差异(180×9/16=101 vs ~200)在 commit 后才暴露,本次修复对齐。

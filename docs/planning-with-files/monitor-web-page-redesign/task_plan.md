# Monitor Web Page Redesign — Task Plan

## 目标

将 monitor_web 侧边栏点击后的空页面 section 填充为真实内容，从「弹窗模式」改为「页面模式」：
- 表格类页面 → 全页面布局（标题 + 工具栏 + 筛选 + 表格 + 分页）
- 配置类页面 → 内嵌卡片布局（页面标题 + 功能区卡片）

## 设计语言

- 背景：var(--bg: #f5f4ed)
- 卡片：var(--surface: #faf9f5)，border-radius: var(--r-lg: 12px)
- 强调色：var(--accent: #c96442)
- 侧边栏：var(--sidebar-bg: #141413)
- 标题字体：Georgia
- 正文字体：Inter / system-ui
- 内边距：20px 24px（main）

## 页面分类

### 全页面布局（表格类）
| 页面 | 说明 |
|------|------|
| page-downloads | 批量下载（上传区+配置区+最近任务表格+进度区） |
| page-proxy-pools | 固定代理管理（表格+Demo视图切换） |
| page-dynamic-providers | 动态代理提供方（调度器状态+表格） |
| page-clip-history | 切片历史（筛选+表格+分页） |

### 内嵌卡片布局（配置类）
| 页面 | 说明 |
|------|------|
| page-api-keys | API Keys（全卡片列表） |
| page-settings | 全局配置（多个配置区块卡片） |

### 保持不变
| 页面 | 说明 |
|------|------|
| page-dashboard | 数据概览已有内容 |
| page-channels | 账户管理已有内容 |

## 实现步骤

- [ ] 1. 重写 page-downloads（批量下载）
- [ ] 2. 重写 page-proxy-pools（固定代理）
- [ ] 3. 重写 page-dynamic-providers（动态代理）
- [ ] 4. 重写 page-clip-history（切片历史）
- [ ] 5. 重写 page-api-keys（API Keys）
- [ ] 6. 重写 page-settings（全局配置）
- [ ] 7. 清理 app.js 中的 PAGE_MODAL_MAP（旧逻辑）
- [ ] 8. 验证所有侧边栏导航正常工作

## 设计规格

### 全页面布局标准结构
```
.page-{name}
  .page-header
    .page-title + .page-desc
    .page-actions (right-aligned)
  .page-toolbar (filters, search, view toggles)
  .table-wrap / .table-container
  .page-pagination
```

### 内嵌卡片布局标准结构
```
.page-{name}
  .page-header
  .card (功能区块1)
    .card-header + .card-body
  .card (功能区块2)
    .card-header + .card-body
```

### 共享样式
- `.page-header`: padding 0 0 16px, display flex justify-content space-between
- `.page-title`: font-family Georgia, font-size 20px, font-weight 600
- `.page-actions`: display flex gap 8px
- `.page-toolbar`: display flex gap 12px align-items center, padding 12px 16px bg surface2 rounded

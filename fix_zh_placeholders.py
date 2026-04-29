#!/usr/bin/env python3
"""Fill all remaining [ZH:xxx] placeholder keys in zh.json with Chinese translations."""
import json

with open(r'D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\static\i18n\zh.json', 'r', encoding='utf-8') as f:
    zh = json.load(f)

# Comprehensive translation map for remaining placeholders
trans = {
    # account
    'accountOnlyProxyMustEnable': '仅代理模式需启用动态代理',
    'noDefaultKey': '— 无默认 Key —',
    # batch
    'browsePathHint': '选择保存目录',
    'browsePathPlaceholder': '选择目录',
    'browsePathTitle': '浏览',
    'btnCancel': '取消',
    'btnClose': '关闭',
    'btnConfirm': '确认',
    'btnReopen': '重新打开',
    'btnStartDownload': '开始下载',
    'cancelFailed': '取消失败',
    'cancelingDownload': '正在取消下载',
    'cancelled': '已取消',
    'cancelledMsg': '任务已取消',
    'cancelledStatus': '已取消',
    'cancelling': '正在取消',
    'cancellingTask': '正在取消任务',
    'checkCookieProxy': '检查 Cookie 和代理',
    'collapseLog': '收起日志',
    'completed': '已完成',
    'doneStatus': '已完成',
    'downloadError': '下载出错',
    'downloadInProgress': '下载进行中',
    'downloadingStatus': '下载中',
    'errorStatus': '出错',
    'expandLog': '展开日志',
    'failure': '失败',
    'finished': '已完成',
    'inProgress': '进行中',
    'invalidTask': '无效任务',
    'loadTaskFailed': '加载任务失败',
    'noBatchTask': '无批量任务',
    'noFileRecorded': '无文件记录',
    'noneRecentTask': '无最近任务',
    'openResult': '打开结果',
    'pending': '待处理',
    'previewCount': '预览 {n} 条',
    'recentSummary': '总计 {total} · 进行中 {active} · 已完成 {done} · 已取消 {cancelled}',
    'recentTaskHint': '可恢复查看运行中任务，或打开最近完成/取消的任务结果。',
    'requestingCancel': '请求取消中',
    'restartFailed': '重启失败',
    'retryCount': '重试次数',
    'retryDone': '重试完成',
    'retryInProgress': '重试中',
    'retryRequestFailed': '重试请求失败',
    'runningTasks': '运行中任务',
    'startupInProgress': '启动中',
    'submitting': '提交中',
    'systemDefault': '（按系统默认）',
    'taskEmpty': '任务为空',
    'taskLoaded': '任务已加载',
    'taskSnapshotCancelled': '快照：任务已取消',
    'taskSnapshotFailed': '快照：部分失败',
    'taskSnapshotPartial': '快照：部分成功',
    'taskSnapshotSuccess': '快照：成功',
    'timeUnknown': '未知',
    # cache
    'confirmDeleteCache': '删除缓存',
    'confirmDeleteCacheMsg': '确定删除该缓存项吗？',
    'deleteFailed': '删除失败',
    'enterApiKey': '请输入 API Key',
    'handleAndApiKeyRequired': 'handle 和 API Key 均必填',
    'noCache': '暂无缓存',
    # clip
    'clipPending': '等待切片',
    'clipPlay': '播放切片',
    'createFailed': '创建切片失败',
    'pageLoading': '页面加载中...',
    'requestFailed': '请求失败',
    'scoreLabel': '评分',
    'taskCreated': '切片任务已创建',
    'totalClips': '{n} 个切片',
    'unknownVideo': '未知视频',
    # provider
    'refreshError': '刷新失败',
    'toggleCollapse': '收起',
    'toggleExpand': '展开',
    # proxy
    'deletedWithAccounts': '已删除（含关联账户）',
    'notFound': '节点不存在',
    'saveFailed': '保存失败',
    'statusOffline': '离线',
    'statusOnline': '在线',
    # scheduler
    'execDone': '执行完成',
    'execFailed': '执行失败',
    'operationFailed': '操作失败',
    'refreshAllProviders': '刷新全部提供方',
    'refreshAllProvidersMsg': '立即对所有提供方执行一次健康检查和列表刷新',
    'refreshNow': '立即刷新',
    'reloadDone': '重载完成',
    'reloadFailed': '重载失败',
    'schedulerAlreadyRunning': '调度器已在运行',
    'schedulerAlreadyRunningAuto': '调度器已在运行（自动下载已开启）',
    'schedulerAlreadyRunningNoAuto': '调度器已在运行（自动下载未开启）',
    'startFailed': '启动失败',
    'startMonitorDesc': '启动后将按计划间隔自动扫描各账户',
    'startScheduler': '启动调度器',
    'startSchedulerMsg': '启动 Provider Scheduler，按各提供方的刷新间隔自动拉取列表',
    'stopSchedulerMsg': '停止后提供方将不再自动刷新',
    # video
    'batchDone': '批量完成',
    'downloadFailed': '下载失败',
    'downloadingN': '正在下载 {n}...',
    'noRetryable': '无可重试项',
    'pageInfo': '— / — 页',
    'rateLimitHint': '请求过于频繁，请稍后再试',
    'retryConfirm': '确定重试这 {n} 个失败项吗？',
    'retryDone': '重试完成',
    'retryRequestFailed': '重试请求失败',
    'subtitleOff': '字幕关闭',
    'subtitleOn': '字幕开启',
    'tagDownloaded': '已下载',
    'tagDownloading': '下载中',
    'tagFailed': '失败',
    'tagPending': '待下载',
    'totalVideos': '共 {n} 个视频',
    'videosQueued': '{n} 个视频已入队',
}

# Additional translations for keys that exist in multiple sections
extra_trans = {
    ('batch', 'failed'): '失败',
    ('batch', 'noRecentTasks'): '暂无最近任务',
    ('batch', 'noTasksToView'): '无任务可查看',
    ('batch', 'parseFailed'): '解析文件失败',
    ('batch', 'total'): '总计',
    ('batch', 'unknown'): '未知',
    ('clip', 'btnClip'): '切片',
    ('proxy', 'btnDisable'): '禁用',
    ('proxy', 'btnEnable'): '启用',
    ('scheduler', 'schedulerRunning'): '调度器运行中',
    ('scheduler', 'schedulerStartedAuto'): '调度器已启动（自动下载已开启）',
    ('scheduler', 'schedulerStopped'): '调度器已停止',
    ('scheduler', 'stopScheduler'): '停止调度器',
    ('video', 'btnClip'): '切片',
    ('video', 'btnDownloadSelected'): '下载选中 ({n})',
    ('video', 'downloadAbnormal'): '下载异常: {e}',
    ('video', 'downloadComplete'): '下载完成',
    ('video', 'queryFailed'): '查询失败: {e}',
    ('video', 'routingCurrent'): '本次线路: {s}',
}

fixed = 0
for section in zh:
    if not isinstance(zh[section], dict):
        continue
    for key in list(zh[section].keys()):
        val = zh[section][key]
        if isinstance(val, str) and val.startswith('[ZH:') and val.endswith(']'):
            actual_key = val[4:-1]
            if actual_key in trans:
                zh[section][key] = trans[actual_key]
                fixed += 1
            elif key in trans:
                zh[section][key] = trans[key]
                fixed += 1
            elif (section, key) in extra_trans:
                zh[section][key] = extra_trans[(section, key)]
                fixed += 1

print(f'Fixed {fixed} placeholder keys')

# Check remaining
remaining = []
for section in zh:
    if isinstance(zh[section], dict):
        for k, v in zh[section].items():
            if isinstance(v, str) and v.startswith('[ZH:'):
                remaining.append(f'{section}.{k}')

print(f'Remaining placeholders: {len(remaining)}')
for r in sorted(remaining):
    print(f'  {r}')

output = json.dumps(zh, ensure_ascii=False, indent=2)
with open(r'D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\static\i18n\zh.json', 'w', encoding='utf-8') as f:
    f.write(output)

with open(r'D:\WORKSPACE\video-download-space\ytdlp-batch-downloader\monitor_web\static\i18n\zh.json', 'r', encoding='utf-8') as f:
    json.load(f)
print('VALIDATION: zh.json is valid JSON')

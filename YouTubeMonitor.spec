# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for YouTubeMonitor.exe
构建:  pyinstaller YouTubeMonitor.spec
"""
import os
import sys

root = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['monitor_server.py'],
    pathex=[root],
    binaries=[],
    datas=[
        ('monitor', 'monitor'),
        ('monitor_web', 'monitor_web'),
    ],
    hiddenimports=[
        'apscheduler',
        'apscheduler.schedulers',
        'apscheduler.schedulers.background',
        'apscheduler.triggers',
        'apscheduler.triggers.interval',
        'requests',
        'googleapiclient',
        'googleapiclient.discovery',
        'tenacity',
        'pandas',
        'openpyxl',
        # monitor 包内部模块
        'monitor',
        'monitor.db',
        'monitor.fetcher',
        'monitor.detector',
        'monitor.notifier',
        'monitor.scheduler',
        'monitor.cache',
        'monitor.quota',
        # refactored packages
        'utils',
        'utils.paths',
        'config',
        'config.settings',
        'config.encryption',
        'config.validation',
        # monitor.db subpackage
        'monitor.db.connection',
        'monitor.db.db_core',
        'monitor.db.migrations',
        'monitor.db.crypto',
        'monitor.db.queries',
        'monitor.db.queries.__init__',
        'monitor.db.queries.accounts',
        'monitor.db.queries.api_keys',
        'monitor.db.queries.candidates',
        'monitor.db.queries.events',
        'monitor.db.queries.logs',
        'monitor.db.queries.providers',
        'monitor.db.queries.proxy_pools',
        'monitor.db.queries.videos',
        'monitor.db.queries.web_batch',
        # HTTP 服务器
        'monitor_server',
        # server package (Phase 2)
        'server',
        'server.__init__',
        'server.__main__',
        'server.download_task',
        'server.batch_store',
        'server.middleware',
        'server.middleware.__init__',
        'server.middleware.rate_limit',
        'server.middleware.auth',
        'server.routes',
        'server.routes.__init__',
        'server.routes.accounts',
        'server.routes.batch',
        'server.routes.providers',
        'server.routes.system',
        # monitor.notification (Phase 3)
        'monitor.notification',
        'monitor.notification.__init__',
        'monitor.notification.base',
        'monitor.notification.feishu',
        'monitor.notification.dingtalk',
        'monitor.notification.wecom',
        'monitor.notification.renderers',
        # monitor.proxy (Phase 3)
        'monitor.proxy',
        'monitor.proxy.__init__',
        'monitor.proxy.models',
        'monitor.proxy.providers',
        'monitor.proxy.router',
        # ytb_api 依赖
        'ytb_api',
        'logging_config',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YouTubeMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # GUI 程序，无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

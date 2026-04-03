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
        # HTTP 服务器
        'monitor_server',
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

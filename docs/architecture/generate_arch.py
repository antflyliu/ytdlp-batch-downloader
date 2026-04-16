#!/usr/bin/env python3
lines = []
lines.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 800" width="960" height="800">')
lines.append('  <style>')
lines.append('    text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif; }')
lines.append('  </style>')
lines.append('  <defs>')
lines.append('    <marker id="arrow-claude" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">')
lines.append('      <polygon points="0 0, 8 4, 0 8" fill="#5a5a5a"/>')
lines.append('    </marker>')
lines.append('    <filter id="shadow-soft">')
lines.append('      <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#00000010"/>')
lines.append('    </filter>')
lines.append('  </defs>')
lines.append('  <rect width="960" height="800" fill="#f8f6f3"/>')
lines.append('  <text x="480" y="35" text-anchor="middle" fill="#1a1a1a" font-size="22" font-weight="700">YouTube Monitor 架构图</text>')
lines.append('  <text x="480" y="58" text-anchor="middle" fill="#6a6a6a" font-size="13">ytdlp-batch-downloader | 基于 yt-dlp 的 YouTube 工具集</text>')

# Layer labels
lines.append('  <text x="25" y="100" fill="#6a6a6a" font-size="14" font-weight="600">用户层</text>')
lines.append('  <text x="25" y="260" fill="#6a6a6a" font-size="14" font-weight="600">服务层</text>')
lines.append('  <text x="25" y="420" fill="#6a6a6a" font-size="14" font-weight="600">核心业务</text>')
lines.append('  <text x="25" y="600" fill="#6a6a6a" font-size="14" font-weight="600">数据层</text>')
lines.append('  <text x="25" y="740" fill="#6a6a6a" font-size="14" font-weight="600">外部集成</text>')

# User Layer
lines.append('  <rect x="60" y="110" width="140" height="70" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="130" y="145" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">GUI</text>')
lines.append('  <text x="130" y="162" text-anchor="middle" fill="#6a6a6a" font-size="11">ytdownload_ui.py</text>')
lines.append('  <text x="130" y="176" text-anchor="middle" fill="#6a6a6a" font-size="11">monitor_ui.py</text>')

lines.append('  <rect x="230" y="110" width="140" height="70" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="300" y="145" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Web UI</text>')
lines.append('  <text x="300" y="162" text-anchor="middle" fill="#6a6a6a" font-size="11">monitor_web/</text>')
lines.append('  <text x="300" y="176" text-anchor="middle" fill="#6a6a6a" font-size="11">HTML + Vanilla JS</text>')

lines.append('  <rect x="400" y="110" width="140" height="70" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="470" y="145" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">CLI</text>')
lines.append('  <text x="470" y="162" text-anchor="middle" fill="#6a6a6a" font-size="11">Youtube_Downloader.py</text>')
lines.append('  <text x="470" y="176" text-anchor="middle" fill="#6a6a6a" font-size="11">scripts/cli.py</text>')

# Server Layer
lines.append('  <rect x="60" y="230" width="200" height="80" rx="12" ry="12" fill="#f4e4c1" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="160" y="265" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">REST API Server</text>')
lines.append('  <text x="160" y="282" text-anchor="middle" fill="#6a6a6a" font-size="11">server/__main__.py</text>')
lines.append('  <text x="160" y="296" text-anchor="middle" fill="#6a6a6a" font-size="11">monitor_server.py</text>')

lines.append('  <rect x="290" y="230" width="160" height="80" rx="12" ry="12" fill="#f4e4c1" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="370" y="265" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Middleware</text>')
lines.append('  <text x="370" y="282" text-anchor="middle" fill="#6a6a6a" font-size="11">Auth (Bearer Token)</text>')
lines.append('  <text x="370" y="296" text-anchor="middle" fill="#6a6a6a" font-size="11">Rate Limiting</text>')

lines.append('  <rect x="480" y="230" width="160" height="80" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="560" y="265" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Download Manager</text>')
lines.append('  <text x="560" y="282" text-anchor="middle" fill="#6a6a6a" font-size="11">_DownloadTaskManager</text>')
lines.append('  <text x="560" y="296" text-anchor="middle" fill="#6a6a6a" font-size="11">Task cancel/progress</text>')

# Core Business Layer
lines.append('  <rect x="60" y="370" width="160" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="140" y="405" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Scheduler</text>')
lines.append('  <text x="140" y="422" text-anchor="middle" fill="#6a6a6a" font-size="11">APScheduler</text>')
lines.append('  <text x="140" y="436" text-anchor="middle" fill="#6a6a6a" font-size="11">定时扫描</text>')

lines.append('  <rect x="240" y="370" width="160" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="320" y="405" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Fetcher</text>')
lines.append('  <text x="320" y="422" text-anchor="middle" fill="#6a6a6a" font-size="11">YouTube Data API</text>')
lines.append('  <text x="320" y="436" text-anchor="middle" fill="#6a6a6a" font-size="11">playlist/search</text>')

lines.append('  <rect x="420" y="370" width="160" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="500" y="405" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Notifier</text>')
lines.append('  <text x="500" y="422" text-anchor="middle" fill="#6a6a6a" font-size="11">通知分发</text>')
lines.append('  <text x="500" y="436" text-anchor="middle" fill="#6a6a6a" font-size="11">Feishu/DingTalk/TG</text>')

lines.append('  <rect x="600" y="370" width="140" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="670" y="405" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Quota</text>')
lines.append('  <text x="670" y="422" text-anchor="middle" fill="#6a6a6a" font-size="11">API 配额管理</text>')
lines.append('  <text x="670" y="436" text-anchor="middle" fill="#6a6a6a" font-size="11">per-key 配额</text>')

lines.append('  <rect x="60" y="460" width="200" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="160" y="495" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Proxy Router</text>')
lines.append('  <text x="160" y="512" text-anchor="middle" fill="#6a6a6a" font-size="11">proxy_router.py</text>')
lines.append('  <text x="160" y="526" text-anchor="middle" fill="#6a6a6a" font-size="11">动态代理选择/轮换</text>')

lines.append('  <rect x="280" y="460" width="180" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="370" y="495" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Proxy Provider</text>')
lines.append('  <text x="370" y="512" text-anchor="middle" fill="#6a6a6a" font-size="11">provider_scheduler</text>')
lines.append('  <text x="370" y="526" text-anchor="middle" fill="#6a6a6a" font-size="11">动态代理刷新/健康检测</text>')

lines.append('  <rect x="480" y="460" width="180" height="70" rx="12" ry="12" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="570" y="495" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Notification Adapters</text>')
lines.append('  <text x="570" y="512" text-anchor="middle" fill="#6a6a6a" font-size="11">feishu/dingtalk/telegram/wecom</text>')
lines.append('  <text x="570" y="526" text-anchor="middle" fill="#6a6a6a" font-size="11">Webhook 消息构建</text>')

# Data Layer
lines.append('  <rect x="60" y="580" width="180" height="70" rx="12" ry="12" fill="#e8e6e3" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="150" y="615" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">SQLite DB</text>')
lines.append('  <text x="150" y="632" text-anchor="middle" fill="#6a6a6a" font-size="11">monitor_accounts</text>')
lines.append('  <text x="150" y="646" text-anchor="middle" fill="#6a6a6a" font-size="11">api_keys / api_quota_usage</text>')

lines.append('  <rect x="260" y="580" width="180" height="70" rx="12" ry="12" fill="#e8e6e3" stroke="#4a4a4a" stroke-width="2.5" filter="url(#shadow-soft)"/>')
lines.append('  <text x="350" y="615" text-anchor="middle" fill="#1a1a1a" font-size="14" font-weight="600">Config Files</text>')
lines.append('  <text x="350" y="632" text-anchor="middle" fill="#6a6a6a" font-size="11">config.json / monitor/config.json</text>')
lines.append('  <text x="350" y="646" text-anchor="middle" fill="#6a6a6a" font-size="11">proxy_config.json</text>')

# External Integrations
lines.append('  <rect x="60" y="720" width="160" height="50" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5"/>')
lines.append('  <text x="140" y="750" text-anchor="middle" fill="#1a1a1a" font-size="13" font-weight="600">YouTube Data API v3</text>')

lines.append('  <rect x="240" y="720" width="140" height="50" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5"/>')
lines.append('  <text x="310" y="750" text-anchor="middle" fill="#1a1a1a" font-size="13" font-weight="600">yt-dlp</text>')

lines.append('  <rect x="400" y="720" width="200" height="50" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5"/>')
lines.append('  <text x="500" y="750" text-anchor="middle" fill="#1a1a1a" font-size="13" font-weight="600">Feishu | DingTalk | Telegram</text>')

lines.append('  <rect x="620" y="720" width="160" height="50" rx="12" ry="12" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="2.5"/>')
lines.append('  <text x="700" y="750" text-anchor="middle" fill="#1a1a1a" font-size="13" font-weight="600">Proxy Providers</text>')

# Arrows
lines.append('  <line x1="130" y1="180" x2="130" y2="230" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="300" y1="180" x2="300" y2="230" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="470" y1="180" x2="470" y2="230" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')

lines.append('  <line x1="160" y1="310" x2="160" y2="370" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="370" y1="310" x2="370" y2="370" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="560" y1="310" x2="560" y2="370" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')

lines.append('  <line x1="150" y1="530" x2="150" y2="580" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="350" y1="530" x2="350" y2="580" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')

lines.append('  <line x1="140" y1="440" x2="140" y2="720" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="320" y1="440" x2="310" y2="720" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="500" y1="440" x2="500" y2="720" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')
lines.append('  <line x1="670" y1="440" x2="700" y2="720" stroke="#5a5a5a" stroke-width="2" marker-end="url(#arrow-claude)"/>')

# Legend
lines.append('  <rect x="740" y="650" width="200" height="120" rx="8" ry="8" fill="#ffffff" stroke="#4a4a4a" stroke-width="1.5"/>')
lines.append('  <text x="750" y="670" fill="#1a1a1a" font-size="13" font-weight="600">图例</text>')
lines.append('  <rect x="750" y="680" width="16" height="16" rx="3" fill="#a8c5e6" stroke="#4a4a4a" stroke-width="1"/>')
lines.append('  <text x="775" y="693" fill="#6a6a6a" font-size="11">用户/输入</text>')
lines.append('  <rect x="750" y="702" width="16" height="16" rx="3" fill="#9dd4c7" stroke="#4a4a4a" stroke-width="1"/>')
lines.append('  <text x="775" y="715" fill="#6a6a6a" font-size="11">核心业务</text>')
lines.append('  <rect x="750" y="724" width="16" height="16" rx="3" fill="#f4e4c1" stroke="#4a4a4a" stroke-width="1"/>')
lines.append('  <text x="775" y="737" fill="#6a6a6a" font-size="11">服务/基础设施</text>')
lines.append('  <rect x="750" y="746" width="16" height="16" rx="3" fill="#e8e6e3" stroke="#4a4a4a" stroke-width="1"/>')
lines.append('  <text x="775" y="759" fill="#6a6a6a" font-size="11">存储/数据</text>')

lines.append('</svg>')

with open('D:/WORKSPACE/video-download-space/ytdlp-batch-downloader/docs/architecture/architecture.svg', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print("SVG generated successfully")

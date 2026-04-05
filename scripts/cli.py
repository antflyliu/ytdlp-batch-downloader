"""
统一 CLI 入口 — yt-dlp-batch-downloader
用法:
    python scripts/cli.py deps              # 检查依赖 (--json 输出 JSON)
    python scripts/cli.py check-url URL     # 检测 URL 是否可下载
    python scripts/cli.py download -i URLS -o OUT -r 1080p
    python scripts/cli.py monitor start/stop/once/list/stats/events
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 项目根目录 → 确保能 import 根目录的模块
_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# deps — 依赖检查
# ---------------------------------------------------------------------------

def cmd_deps(json_output: bool = False) -> int:
    """检查 yt-dlp / aria2c / ffmpeg 依赖是否可用。返回 0=全部OK, 1=有缺失."""
    results: list[dict] = []

    # yt-dlp
    ytdlp_info = _check_yt_dlp()
    results.append(ytdlp_info)

    # aria2c
    aria2_info = _check_aria2()
    results.append(aria2_info)

    # ffmpeg
    ffmpeg_info = _check_ffmpeg()
    results.append(ffmpeg_info)

    # whisperx (optional)
    whisper_info = _check_whisperx()
    results.append(whisper_info)

    if json_output:
        print(json.dumps({
            "all_ok": all(r["available"] for r in results),
            "tools": results,
        }, ensure_ascii=False, indent=2))
    else:
        print("=== 依赖检查 ===")
        for tool in results:
            status = "✓" if tool["available"] else "✗"
            version = tool.get("version", "—")
            note = f" ({tool.get('note', '')})" if tool.get("note") else ""
            print(f"  {status} {tool['name']:>10}  {version}{note}")

        missing = [r["name"] for r in results if not r["available"]]
        if missing:
            print(f"\n⚠  缺失: {', '.join(missing)}")
            return 1
        print("\n✅ 所有必需依赖已就绪")
    return 0


def _check_yt_dlp() -> dict:
    try:
        proc = subprocess.run(
            ["python", "-c", "import yt_dlp; print(yt_dlp.version.__version__)"],
            capture_output=True, text=True, timeout=15,
        )
        version = proc.stdout.strip() if proc.returncode == 0 else "unknown"
        return {"name": "yt-dlp", "available": True, "version": version}
    except Exception as e:
        return {"name": "yt-dlp", "available": False,
                "version": "—", "note": str(e)[:80]}


def _check_aria2() -> dict:
    path = shutil.which("aria2c")
    if not path:
        return {"name": "aria2c", "available": False, "version": "—",
                "note": "未找到 aria2c，请安装并加入 PATH"}
    try:
        proc = subprocess.run(["aria2c", "--version"],
                             capture_output=True, text=True, timeout=10)
        first_line = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
        version = first_line.strip()
        return {"name": "aria2c", "available": True, "version": version}
    except Exception as e:
        return {"name": "aria2c", "available": False, "version": "—",
                "note": str(e)[:80]}


def _check_ffmpeg() -> dict:
    path = shutil.which("ffmpeg")
    if not path:
        return {"name": "ffmpeg", "available": False, "version": "—",
                "note": "未找到 ffmpeg，请安装并加入 PATH"}
    try:
        proc = subprocess.run(["ffmpeg", "-version"],
                             capture_output=True, text=True, timeout=10)
        first_line = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
        version = first_line.replace("ffmpeg version", "").strip().split(" ")[0]
        return {"name": "ffmpeg", "available": True, "version": version}
    except Exception as e:
        return {"name": "ffmpeg", "available": False, "version": "—",
                "note": str(e)[:80]}


def _check_whisperx() -> dict:
    try:
        proc = subprocess.run(
            ["python", "-c", "import whisper; print('ok')"],
            capture_output=True, text=True, timeout=15,
        )
        available = proc.returncode == 0
        note = "" if available else "WhisperX 未安装，跳过 ASR 字幕生成"
        return {"name": "whisperx", "available": available,
                "version": "optional", "note": note}
    except Exception:
        return {"name": "whisperx", "available": False,
                "version": "optional", "note": "WhisperX 未安装，跳过 ASR 字幕生成"}


# ---------------------------------------------------------------------------
# check-url — URL 可下载性检测
# ---------------------------------------------------------------------------

def cmd_check_url(url: str, json_output: bool = False) -> int:
    """使用 yt-dlp --dump-json 检测 URL 是否可下载。返回 0=OK, 1=失败."""
    try:
        import yt_dlp

        class InfoGrabber(yt_dlp.YoutubeDL):
            def __init__(self):
                super().__init__({"quiet": True, "no_warnings": True,
                                  "skip_download": True, "extract_flat": False})
                self.info = None

            def grab(self, url):
                with self as ydl:
                    self.info = ydl.extract_info(url, download=False)
                return self.info

        grabber = InfoGrabber()
        info = grabber.grab(url)

        if json_output:
            print(json.dumps({
                "ok": True,
                "url": url,
                "title": info.get("title", "—"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader", "—"),
                "upload_date": info.get("upload_date", "—"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "webpage_url": info.get("webpage_url", url),
            }, ensure_ascii=False, indent=2))
        else:
            print(f"✓ URL 可下载")
            print(f"  标题: {info.get('title', '—')}")
            print(f"  作者: {info.get('uploader', '—')}")
            print(f"  时长: {_fmt_duration(info.get('duration'))}")
            print(f"  上传: {info.get('upload_date', '—')}")
            print(f"  链接: {info.get('webpage_url', url)}")
        return 0
    except Exception as e:
        if json_output:
            print(json.dumps({"ok": False, "url": url, "error": str(e)}, ensure_ascii=False, indent=2))
        else:
            print(f"✗ URL 检测失败: {e}")
        return 1


def _fmt_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"


# ---------------------------------------------------------------------------
# download — 批量下载（委托给 Youtube_Downloader.py）
# ---------------------------------------------------------------------------

def cmd_download(args: argparse.Namespace, json_output: bool = False) -> int:
    """委托给 Youtube_Downloader.batch_download"""
    from Youtube_Downloader import (
        batch_download,
        read_urls_from_file,
        build_aria2_opts,
        load_proxy_pool,
    )

    # 解析 URL 输入
    if os.path.isfile(args.input):
        urls = read_urls_from_file(args.input)
        if not urls:
            print("错误：无法从文件读取 URL" if not json_output
                  else json.dumps({"ok": False, "error": "无法从文件读取 URL"}))
            return 1
    else:
        urls = [u.strip() for u in args.input.split(",") if u.strip()]
        if not urls:
            print("错误：没有有效 URL" if not json_output
                  else json.dumps({"ok": False, "error": "没有有效 URL"}))
            return 1

    if args.max and args.max > 0:
        urls = urls[:args.max]

    output_path = os.path.abspath(args.output)
    os.makedirs(output_path, exist_ok=True)

    # aria2 选项
    extra_opts = {} if args.no_aria2 else build_aria2_opts(proxy=args.proxy)
    if args.proxy:
        extra_opts["proxy"] = args.proxy

    # 代理池
    proxy_pool = None
    if args.proxy_file:
        proxy_pool = load_proxy_pool(args.proxy_file)

    # 开始下载
    try:
        results = batch_download(
            urls=urls,
            output_path=output_path,
            resolution=args.resolution,
            proxy=args.proxy if not args.proxy_file else None,
            sub_langs=None if args.no_subs else args.sub_lang,
            no_subs=args.no_subs,
            proxy_pool=proxy_pool,
            cookies_from_browser=args.cookies_from_browser,
            cookies_file=args.cookies,
            concurrent_fragments=args.concurrent_fragments,
            extra_ydl_opts=extra_opts if extra_opts else None,
        )
    except Exception as e:
        if json_output:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"下载异常: {e}")
        return 1

    success = sum(1 for r in results if r.get("状态") == "成功")

    if json_output:
        print(json.dumps({
            "ok": True,
            "total": len(results),
            "success": success,
            "failed": len(results) - success,
            "results": results,
        }, ensure_ascii=False, indent=2))
    else:
        from Youtube_Downloader import save_results_to_excel
        save_results_to_excel(results, output_path)
        print(f"\n✅ 下载完成！成功: {success}/{len(results)}")
    return 0


# ---------------------------------------------------------------------------
# monitor — 监控子命令（委托给 monitor/__main__.py）
# ---------------------------------------------------------------------------

def cmd_monitor(args: argparse.Namespace, json_output: bool = False) -> int:
    """将监控子命令转发给 monitor/__main__.py"""
    # 构造等价的 sys.argv 供 monitor/__main__.py 解析
    monitor_cmd = [args.monitor_cmd] + args.extra
    old_argv = sys.argv
    sys.argv = ["monitor"] + monitor_cmd
    try:
        from monitor import __main__ as monitor_main
        monitor_main.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        if json_output:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"监控命令异常: {e}")
        return 1
    finally:
        sys.argv = old_argv


# ---------------------------------------------------------------------------
# 通用 stats / events / list（直接查库）
# ---------------------------------------------------------------------------

def cmd_stats(json_output: bool = False) -> int:
    from monitor import db as _db
    _db.init_db()
    rows = _db.get_account_stats()
    if not rows:
        msg = "无统计数据"
        print(msg if not json_output else json.dumps({"ok": True, "stats": []}))
        return 0
    if json_output:
        print(json.dumps({"ok": True, "stats": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"{'ID':>3}  {'名称':<12} {'扫描':>6} {'新视频':>8} {'最后扫描'}")
        print("-" * 60)
        for r in rows:
            last = r["last_scan_at"] or "从未"
            print(f"{r['id']:>3}  {r['name']:<12} {r['total_scans']:>6} "
                  f"{r['total_new_videos']:>8}  {last}")
    return 0


def cmd_events(limit: int, json_output: bool = False) -> int:
    from monitor import db as _db
    _db.init_db()
    evs = _db.get_recent_events(limit)
    if not evs:
        msg = "暂无扫描记录"
        print(msg if not json_output else json.dumps({"ok": True, "events": []}))
        return 0
    if json_output:
        print(json.dumps({"ok": True, "events": evs}, ensure_ascii=False, indent=2))
    else:
        print(f"{'ID':>4}  {'账户':<10} {'状态':<8} {'总数':>4} {'新增':>4} {'耗时'}")
        print("-" * 65)
        for e in evs:
            dur = f"{e['duration_ms']}ms" if e["duration_ms"] else "—"
            print(f"{e['id']:>4}  {e['account_name']:<10} {e['status']:<8} "
                  f"{e['total_videos']:>4}  {e['new_videos']:>4}  {dur}")
    return 0


def cmd_list_accounts(json_output: bool = False) -> int:
    from monitor import db as _db
    _db.init_db()
    accounts = _db.list_accounts()
    if not accounts:
        msg = "没有已配置的监控账户"
        print(msg if not json_output else json.dumps({"ok": True, "accounts": []}))
        return 0
    if json_output:
        print(json.dumps({"ok": True, "accounts": accounts}, ensure_ascii=False, indent=2))
    else:
        print(f"{'ID':>3}  {'名称':<12} {'频道':<30} {'间隔':>4} {'启用'}")
        print("-" * 70)
        for a in accounts:
            print(f"{a['id']:>3}  {a['name']:<12} {a['channel_url']:<30} "
                  f"{a['scan_interval']:>4}m  {'✓' if a['enabled'] else '✗'}")
    return 0


def cmd_quota(api_key_env: str | None, json_output: bool = False) -> int:
    """查询 API Quota 使用情况"""
    from monitor import quota as _quota

    if api_key_env:
        usage = _quota.get_usage(api_key_env)
        budget = _quota.get_budget_limit(api_key_env)
        percent = int(usage["api_calls"] / budget * 100) if budget > 0 else 0
        if json_output:
            print(json.dumps({
                "ok": True,
                "api_key_env": api_key_env,
                "date": usage["date_key"],
                "api_calls": usage["api_calls"],
                "budget": budget,
                "percent": percent,
                "scans_done": usage["scans_done"],
                "blocked_scans": usage["blocked_scans"],
            }, ensure_ascii=False, indent=2))
        else:
            print(f"API Key: {api_key_env}  日期: {usage['date_key']}")
            print(f"  已用: {usage['api_calls']} / {budget} ({percent}%)")
            print(f"  扫描: {usage['scans_done']} 次  已阻止: {usage['blocked_scans']} 次")
            if percent >= 90:
                print("  ⚠  Quota 即将耗尽，请关注！")
    else:
        rows = _quota.get_all_usage()
        if json_output:
            print(json.dumps({"ok": True, "quotas": rows}, ensure_ascii=False, indent=2))
        else:
            if not rows:
                print("今日无 Quota 记录")
            else:
                print(f"{'API Key':<30} {'已用':>8} {'扫描':>6} {'已阻':>6} {'更新时间'}")
                print("-" * 70)
                for r in rows:
                    budget = _quota.get_budget_limit(r["api_key_env"])
                    pct = int(r["api_calls"] / budget * 100) if budget > 0 else 0
                    print(f"{r['api_key_env']:<30} {r['api_calls']:>7} {r['scans_done']:>6} "
                          f"{r['blocked_scans']:>6}  {r.get('updated_at', '—')[:19]}")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="yt-dlp-batch-downloader 统一 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # deps
    p_deps = sub.add_parser("deps", help="检查 yt-dlp / aria2c / ffmpeg 依赖")
    p_deps.add_argument("--json", action="store_true")

    # check-url
    p_url = sub.add_parser("check-url", help="检测 URL 是否可下载")
    p_url.add_argument("url", help="视频 URL")
    p_url.add_argument("--json", action="store_true")

    # download
    p_dl = sub.add_parser("download", help="批量下载视频（委托给 Youtube_Downloader）")
    p_dl.add_argument("--json", action="store_true")
    p_dl.add_argument("-i", "--input", required=True,
                      help="URL 文件 (.xlsx/.txt/.csv) 或逗号分隔 URL")
    p_dl.add_argument("-o", "--output", default="videos",
                      help="下载目录 (默认: videos)")
    p_dl.add_argument("-r", "--resolution", default="1080p",
                      choices=["720p", "1080p", "1440p"],
                      help="视频分辨率 (默认: 1080p)")
    p_dl.add_argument("-p", "--proxy", help="代理地址")
    p_dl.add_argument("-n", "--max", type=int, help="最多下载数量")
    p_dl.add_argument("--no-aria2", action="store_true", help="不使用 aria2c")
    p_dl.add_argument("--concurrent-fragments", type=int, default=4,
                      help="yt-dlp 分片并发数 (默认 4)")
    p_dl.add_argument("--sub-lang", default="zh-Hans,en",
                      help="字幕语言 (默认: zh-Hans,en)")
    p_dl.add_argument("--no-subs", action="store_true", help="不下载字幕")
    p_dl.add_argument("--proxy-file", help="代理池文件（每行一个）")
    p_dl.add_argument("--cookies-from-browser",
                      help="从浏览器读取 cookie")
    p_dl.add_argument("--cookies", help="Cookie 文件路径")

    # monitor
    p_mon = sub.add_parser("monitor", help="监控子命令 (start/stop/once/list/add...)")
    p_mon.add_argument("--json", action="store_true")
    p_mon.add_argument("monitor_cmd", nargs="?", default="list",
                       help="monitor 子命令")
    p_mon.add_argument("extra", nargs=argparse.REMAINDER, default=[],
                       help="额外参数")

    # stats / events / list / quota
    p_stats = sub.add_parser("stats", help="显示账户统计")
    p_stats.add_argument("--json", action="store_true")
    p_evs = sub.add_parser("events", help="显示最近扫描事件")
    p_evs.add_argument("--limit", type=int, default=20)
    p_evs.add_argument("--json", action="store_true")
    p_list = sub.add_parser("list", help="列出所有监控账户")
    p_list.add_argument("--json", action="store_true")
    p_quota = sub.add_parser("quota", help="查询 API Quota 使用情况")
    p_quota.add_argument("--api-key", dest="api_key_env", help="API Key 环境变量名")
    p_quota.add_argument("--json", action="store_true")

    args = parser.parse_args()
    json_output = getattr(args, "json", False)

    # 根据子命令分发
    match args.cmd:
        case "deps":
            return cmd_deps(json_output=json_output)
        case "check-url":
            return cmd_check_url(args.url, json_output=json_output)
        case "download":
            return cmd_download(args, json_output=json_output)
        case "monitor":
            return cmd_monitor(args, json_output=json_output)
        case "stats":
            return cmd_stats(json_output=json_output)
        case "events":
            return cmd_events(args.limit, json_output=json_output)
        case "list":
            return cmd_list_accounts(json_output=json_output)
        case "quota":
            return cmd_quota(getattr(args, "api_key_env", None), json_output=json_output)
        case _:
            parser.print_help()
            return 0


if __name__ == "__main__":
    sys.exit(main())

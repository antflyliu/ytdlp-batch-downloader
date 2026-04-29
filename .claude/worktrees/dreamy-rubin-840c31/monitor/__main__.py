"""
monitor — YouTube 视频监控模块
用法:
    python -m monitor                    # 启动为常驻调度器
    python -m monitor --once             # 单次执行所有账户
    python -m monitor --add "综艺Show" "@C-HitShow" --api-key-env YOUTUBE_Data_API_V3
    python -m monitor --list             # 列出所有账户
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 初始化数据库
import monitor.db as _db

_log = None  # 延迟导入，避免循环


def _get_logger():
    global _log
    if _log is None:
        import logging_config
        _log = logging_config.get_logger("monitor.cli")
    return _log


def _init():
    """初始化：创建数据库 + 加载配置"""
    _db.init_db()
    _db.ensure_app_state_table()

    # 加载全局配置
    config_path = _db.get_config_path()
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def cmd_list():
    accounts = _db.list_accounts()
    if not accounts:
        print("没有已配置的监控账户")
        return
    print(f"{'ID':>3}  {'名称':<12} {'频道':<30} {'间隔':>4} {'启用':>4} {'通知':>4} {'API Key'}")
    print("-" * 90)
    for a in accounts:
        print(
            f"{a['id']:>3}  {a['name']:<12} {a['channel_url']:<30} "
            f"{a['scan_interval']:>4}m  {'✓' if a['enabled'] else '✗':>4}  "
            f"{'✓' if a['notify_enabled'] else '✗':>4}  {a['api_key_env']}"
        )


def cmd_stats():
    rows = _db.get_account_stats()
    if not rows:
        print("无统计数据")
        return
    print(f"{'ID':>3}  {'名称':<12} {'扫描':>6} {'新视频':>8} {'最后扫描':<22}")
    print("-" * 65)
    for r in rows:
        last = r["last_scan_at"] or "从未"
        print(
            f"{r['id']:>3}  {r['name']:<12} {r['total_scans']:>6} "
            f"{r['total_new_videos']:>8}  {last:<22}"
        )


def cmd_events(limit: int = 20):
    events = _db.get_recent_events(limit)
    if not events:
        print("暂无扫描记录")
        return
    print(f"{'ID':>4}  {'账户':<10} {'状态':<8} {'返回':>4} {'新增':>4} {'耗时':>6}  {'开始时间'}")
    print("-" * 80)
    for e in events:
        dur = f"{e['duration_ms']}ms" if e['duration_ms'] else "—"
        print(
            f"{e['id']:>4}  {e['account_name']:<10} {e['status']:<8} "
            f"{e['total_videos']:>4}  {e['new_videos']:>4}  {dur:>6}  {e['scan_started_at'][:19]}"
        )


def cmd_add(args):
    """添加监控账户"""
    _db.init_db()
    try:
        account_id = _db.add_account(
            name=args.name,
            channel_url=args.channel_url,
            api_key_env=args.api_key_env,
            fetch_mode=args.fetch_mode,
            fetch_limit=args.fetch_limit,
            scan_interval=args.scan_interval,
            notify_enabled=not args.no_notify,
            notify_platform=args.notify_platform,
            webhook_url=args.webhook_url or None,
            dingtalk_sign_secret=(args.dingtalk_sign_secret or "").strip() or None,
            feishu_message_mode=args.feishu_mode,
            feishu_template_id=args.feishu_template_id or None,
            feishu_scan_template_id=args.feishu_scan_template_id or None,
        )
    except ValueError as e:
        print(f"✗ 配置错误: {e}")
        raise SystemExit(2) from e
    print(f"✓ 账户添加成功 (id={account_id}): {args.name} @ {args.channel_url} "
          f"[{args.notify_platform}]")
    if args.start:
        _start_scheduler_once()


def cmd_delete(account_id: int):
    _db.delete_account(account_id)
    print(f"✓ 账户已删除: id={account_id}")


def cmd_enable(account_id: int, enabled: bool):
    _db.update_account(account_id, enabled=enabled)
    state = "启用" if enabled else "禁用"
    print(f"✓ 账户 {state}: id={account_id}")
    if _scheduler_module.is_running():
        _scheduler_module.reload_jobs()


def _start_scheduler_once():
    from monitor import scheduler as _scheduler_module
    _scheduler_module.start()
    print("调度器已启动，按 Ctrl+C 退出...")
    try:
        import time
        while _scheduler_module.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        _scheduler_module.stop()


def main():
    parser = argparse.ArgumentParser(
        description="YouTube 视频监控 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # list
    sub.add_parser("list", help="列出所有监控账户")

    # stats
    sub.add_parser("stats", help="显示账户统计")

    # events
    ev = sub.add_parser("events", help="显示最近扫描事件")
    ev.add_argument("--limit", type=int, default=20, help="显示数量 (默认20)")

    # add
    add_p = sub.add_parser("add", help="添加监控账户")
    add_p.add_argument("name", help="显示名称")
    add_p.add_argument("channel_url", help="频道 URL (@xxx / UCxxxx / URL)")
    add_p.add_argument("--api-key-env", default="YOUTUBE_Data_API_V3", help="API Key 环境变量名")
    add_p.add_argument("--fetch-mode", default="playlist", choices=["search", "playlist"], help="获取模式")
    add_p.add_argument("--fetch-limit", type=int, default=5, help="每次获取视频条数")
    add_p.add_argument("--scan-interval", type=int, default=5, help="扫描间隔（分钟）")
    add_p.add_argument("--notify-platform", default="feishu",
                      choices=["feishu", "dingtalk", "wecom"],
                      help="通知平台 (默认飞书)")
    add_p.add_argument("--webhook-url", help="各平台 Webhook URL（可选，留空用全局配置）")
    add_p.add_argument(
        "--dingtalk-sign-secret",
        default="",
        help="钉钉机器人加签密钥 SEC…（可选，与 --webhook-url 成对；仅 notify_platform=dingtalk 时生效）",
    )
    add_p.add_argument("--feishu-mode", default="card_json", choices=["card_json", "template"],
                      help="飞书发送方式 (默认 card_json)")
    add_p.add_argument("--feishu-template-id",
                      help="飞书详情卡片模板 ID（template 模式用）")
    add_p.add_argument("--feishu-scan-template-id",
                      help="飞书扫描确认模板 ID（template 模式用）")
    add_p.add_argument("--no-notify", action="store_true", help="禁用通知")
    add_p.add_argument("--start", action="store_true", help="添加后立即启动调度器")

    # start / stop
    sub.add_parser("start", help="启动调度器")
    sub.add_parser("stop", help="停止调度器")
    sub.add_parser("reload", help="重载任务（扫描新添加的账户）")

    # enable / disable
    en = sub.add_parser("enable", help="启用账户")
    en.add_argument("account_id", type=int, help="账户 ID")
    dis = sub.add_parser("disable", help="禁用账户")
    dis.add_argument("account_id", type=int, help="账户 ID")

    # delete
    del_p = sub.add_parser("delete", help="删除账户")
    del_p.add_argument("account_id", type=int, help="账户 ID")

    # once
    sub.add_parser("once", help="单次执行所有账户（不启动调度器）")

    args = parser.parse_args()

    # 初始化
    config = _init()

    # 根据子命令分发
    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "events":
        cmd_events(args.limit)
    elif args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "delete":
        cmd_delete(args.account_id)
    elif args.cmd == "enable":
        cmd_enable(args.account_id, True)
    elif args.cmd == "disable":
        cmd_enable(args.account_id, False)
    elif args.cmd == "start":
        from monitor import scheduler as sch
        if sch.is_running():
            print("调度器已在运行")
        else:
            sch.start()
            print("调度器已启动，按 Ctrl+C 退出...")
            try:
                import time
                while sch.is_running():
                    time.sleep(1)
            except KeyboardInterrupt:
                sch.stop()
    elif args.cmd == "stop":
        from monitor import scheduler as sch
        sch.stop()
    elif args.cmd == "reload":
        from monitor import scheduler as sch
        if not sch.is_running():
            print("调度器未运行，先执行 start")
        else:
            n = sch.reload_jobs()
            print(f"重载完成，当前活跃任务: {n}")
    elif args.cmd == "once":
        from monitor import scheduler as sch
        accounts = _db.list_accounts(enabled_only=True)
        for acc in accounts:
            print(f"扫描: {acc['name']}")
            sch._scan_account(acc["id"])


if __name__ == "__main__":
    main()

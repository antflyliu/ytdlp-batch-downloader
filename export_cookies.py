#!/usr/bin/env python3
"""
YouTube Cookie 导出与转换工具

支持格式:
  --json FILE     : JSON 格式（YouTube 官网导出）→ 转换为 Netscape 格式
  --verify FILE   : 验证已有 cookies.txt 是否完整

用法:
  # 转换 JSON Cookie 到 yt-dlp 可用的格式
  python export_cookies.py --json cookies.json

  # 验证 Cookie 文件完整性
  python export_cookies.py --verify cookies.txt
"""
import os
import sys
import json
import argparse

IMPORTANT = ["SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO"]
# 只保留 YouTube/Google 相关域名，减少文件体积并避免边界情况
RELEVANT_DOMAINS = {"youtube.com", "googlevideo.com", "google.com", "googleapis.com",
                    "googleusercontent.com", "doubleclick.net", "youtubeeducation.com"}


def _is_relevant(domain: str) -> bool:
    """域名是否与 YouTube 相关"""
    if not domain:
        return False
    d = domain.lower()
    if d in RELEVANT_DOMAINS:
        return True
    # .前缀的子域名也算（.youtube.com 匹配 youtube.com）
    if d.startswith("."):
        d = d[1:]
    return d in RELEVANT_DOMAINS


def _escape_value(value: str) -> str:
    """将 cookie 值中的制表符/换行转义为可打印形式，避免破坏 Netscape 格式"""
    return value.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def convert_json_to_netscape(json_file: str, output_file: str = "cookies.txt") -> bool:
    """
    将 JSON 格式 Cookie（YouTube 官网导出）转换为 Netscape 格式（yt-dlp 可用）
    """
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 读取 JSON 失败: {e}")
        return False

    if not isinstance(data, list):
        print("❌ JSON 格式不正确，期望为数组格式")
        return False

    print(f"📄 共 {len(data)} 个 Cookie")

    netscape = ["# Netscape HTTP Cookie File\n", "# Converted by export_cookies.py\n\n"]
    yt_names = set()
    skipped_relevant = 0
    skipped_empty = 0

    for c in data:
        domain = c.get("domain", "")
        name = c.get("name", "")
        value = _escape_value(c.get("value", "") or "")
        path = c.get("path", "/") or "/"
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expires = int(c.get("expirationDate", 0) or 0)

        # 过滤：只保留 YouTube/Google 相关域名
        if not _is_relevant(domain):
            continue
        # 跳过空值
        if not value:
            skipped_empty += 1
            continue

        # domain_specified: domain 以 "." 开头 → TRUE；否则 FALSE
        # http.cookiejar._really_load() 断言 domain_specified == initial_dot，
        # initial_dot = domain.startswith(".")，两者必须相等
        initial_dot = domain.startswith(".")
        domain_specified = "TRUE" if initial_dot else "FALSE"

        if "youtube" in domain.lower():
            yt_names.add(name)
        netscape.append(
            f"{domain}\t{domain_specified}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n"
        )

    print(f"📄 原始 {len(data)} 个 Cookie → 过滤后 {len(netscape)-2} 个（跳过无关 {len(data)-len(netscape)+2} 个，空值 {skipped_empty} 个）")

    print(f"🔍 YouTube 相关 Cookie: {len(yt_names)} 个")
    for n in IMPORTANT:
        mark = "✅" if n in yt_names else "❌"
        print(f"   {mark} {n}")

    missing = [n for n in IMPORTANT if n not in yt_names]
    if missing:
        print(f"\n⚠️  缺失关键 Cookie: {', '.join(missing)}")
        print("   可能导致 YouTube 仍判定为机器人，建议补充登录凭证")

    with open(output_file, "w", encoding="utf-8") as f:
        f.writelines(netscape)

    size = os.path.getsize(output_file)
    print(f"\n✅ 已转换: {os.path.abspath(output_file)} ({size} bytes)")
    print(f"\n使用方法:")
    print(f"  python Youtube_Downloader.py -i urls.xlsx --cookies {output_file}")
    return True


def verify(cookie_file: str) -> bool:
    """验证 netscape 格式 cookies.txt 是否包含完整登录凭证"""
    if not os.path.exists(cookie_file):
        print(f"❌ 文件不存在: {cookie_file}")
        return False

    with open(cookie_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    netscape = [l for l in lines if l.strip() and not l.startswith("#")]
    if not netscape:
        print("❌ Cookie 文件为空")
        return False

    names = set()
    for line in netscape:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 7:
            names.add(parts[5])

    size = os.path.getsize(cookie_file)
    print(f"📄 文件: {size} bytes, Cookie 数量: {len(netscape)}")
    print(f"📋 Cookie: {', '.join(sorted(names))}")

    missing = [n for n in IMPORTANT if n not in names]
    if missing:
        print(f"\n❌ 缺失关键 Cookie: {', '.join(missing)}")
        return False

    print(f"\n✅ Cookie 完整，可正常使用")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Cookie 导出与转换工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python export_cookies.py --json cookies.json\n"
            "  python export_cookies.py --verify cookies.txt\n"
        )
    )
    parser.add_argument("--output", "-o", metavar="FILE",
                      help="指定输出文件（配合 --json 使用，默认 cookies.txt）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", "-j", metavar="FILE",
                      help="JSON 格式 Cookie（YouTube 官网导出）→ 转换为 Netscape 格式")
    group.add_argument("--verify", "-v", metavar="FILE",
                      help="验证 cookies.txt 是否完整")
    args = parser.parse_args()

    if args.json:
        output = args.output or "cookies.txt"
        ok = convert_json_to_netscape(args.json, output)
        sys.exit(0 if ok else 1)

    if args.verify:
        ok = verify(args.verify)
        sys.exit(0 if ok else 1)

    parser.print_help()


if __name__ == "__main__":
    main()

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
    返回 True 成功，False 失败
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


def convert_json_to_temp_netscape(json_file: str) -> tuple[str, int, list[str]]:
    """
    将 JSON Cookie 转换为临时 Netscape 文件，返回 (文件路径, cookie数量, 缺失关键cookie列表)。
    供 GUI 直接调用，无需指定输出路径。
    """
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="yt_cookies_")
    os.close(fd)
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        os.unlink(tmp_path)
        raise ValueError(f"读取 JSON 失败: {e}")

    netscape = ["# Netscape HTTP Cookie File\n", "# Converted by export_cookies.py\n\n"]
    yt_names: set = set()
    skipped_empty = 0

    for c in data:
        domain = c.get("domain", "")
        name = c.get("name", "")
        value = _escape_value(c.get("value", "") or "")
        path = c.get("path", "/") or "/"
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expires = int(c.get("expirationDate", 0) or 0)
        if not _is_relevant(domain):
            continue
        if not value:
            skipped_empty += 1
            continue
        initial_dot = domain.startswith(".")
        domain_specified = "TRUE" if initial_dot else "FALSE"
        if "youtube" in domain.lower():
            yt_names.add(name)
        netscape.append(
            f"{domain}\t{domain_specified}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n"
        )

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(netscape)

    missing = [n for n in IMPORTANT if n not in yt_names]
    return tmp_path, len(netscape) - 2, missing


# ── Chrome 浏览器自动检测 ──────────────────────────────────────────────────────

def _get_chrome_user_data_dir() -> str:
    """返回 Chrome User Data 目录路径"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        return os.path.join(base, r"Google\Chrome\User Data")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    else:
        return os.path.expanduser("~/.config/google-chrome")


def _get_edge_user_data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
        return os.path.join(base, r"Microsoft\Edge\User Data")
    elif sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Microsoft Edge")
    else:
        return os.path.expanduser("~/.config/microsoft-edge")


def detect_chrome_profile(browser: str = "chrome") -> dict:
    """
    读取 Chrome/Edge Local State，检测最后使用的 Profile 及账号信息。
    返回 {'profile': 'Default', 'email': 'xxx@gmail.com', 'name': '显示名', 'profile_dir': '...'}
    如果 Local State 无法读取（Chrome 正在写入），返回 info_cache 中最后活跃的 Profile。
    """
    if browser == "edge":
        user_data_dir = _get_edge_user_data_dir()
    else:
        user_data_dir = _get_chrome_user_data_dir()

    local_state = os.path.join(user_data_dir, "Local State")
    if not os.path.exists(local_state):
        raise FileNotFoundError(f"未找到 Chrome/Edge：{local_state}")

    with open(local_state, "r", encoding="utf-8") as f:
        state = json.load(f)

    info_cache: dict = state.get("profile", {}).get("info_cache", {})
    if not info_cache:
        raise ValueError("Local State 中无法读取 profile info_cache")

    # 优先用 last_used（Chrome 完全退出后最准确）
    last_used = state.get("last_used")
    if last_used and last_used in info_cache:
        info = info_cache[last_used]
        return {
            "profile": last_used,
            "email": info.get("user_name", ""),
            "name": info.get("gaia_given_name", ""),
            "profile_dir": os.path.join(user_data_dir, last_used),
        }

    # fallback：按 active_time 选最活跃的
    sorted_profiles = sorted(
        info_cache.items(),
        key=lambda x: x[1].get("active_time", 0),
        reverse=True,
    )
    name, info = sorted_profiles[0]
    return {
        "profile": name,
        "email": info.get("user_name", ""),
        "name": info.get("gaia_given_name", ""),
        "profile_dir": os.path.join(user_data_dir, name),
    }


def _read_cookies_db(db_path: str, tmp_path: str) -> set:
    """将 SQLite Cookies 文件复制并解密读取，返回 YouTube 相关 cookie 名称集合"""
    import shutil, sqlite3, tempfile

    shutil.copy2(db_path, tmp_path)
    conn = sqlite3.connect(tmp_path)
    cur = conn.execute(
        "SELECT name FROM cookies WHERE host_key LIKE '%youtube.com' OR host_key LIKE '%google.com'"
    )
    names = {r[0] for r in cur.fetchall()}
    conn.close()
    return names


def extract_chrome_cookies_to_netscape(
    profile: str, browser: str = "chrome"
) -> tuple[str, int, list[str]]:
    """
    读取指定 Profile 的 Chrome/Edge Cookie 数据库，转换为 Netscape 临时文件。
    返回 (临时文件路径, cookie数量, 缺失关键cookie列表)。
    如果 Cookie 文件被锁（Chrome 运行中），抛出异常。
    """
    if browser == "edge":
        user_data_dir = _get_edge_user_data_dir()
    else:
        user_data_dir = _get_chrome_user_data_dir()

    profile_dir = os.path.join(user_data_dir, profile)
    cookie_db = os.path.join(profile_dir, "Network", "Cookies")

    if not os.path.exists(cookie_db):
        raise FileNotFoundError(f"Cookie 数据库不存在：{cookie_db}")

    import sqlite3, shutil, tempfile

    fd, tmp_file = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        shutil.copy2(cookie_db, tmp_file)
    except OSError as e:
        os.unlink(tmp_file)
        raise OSError(f"Cookie 文件被锁定（Chrome 正在运行）：{e}") from e

    conn = sqlite3.connect(tmp_file)
    is_secure_col = _column_exists(conn, "cookies", "is_secure")
    secure_col = "is_secure" if is_secure_col else "secure"
    rows = conn.execute(
        f"SELECT host_key, name, value, path, expires_utc, {secure_col} FROM cookies"
    ).fetchall()
    conn.close()
    os.unlink(tmp_file)

    netscape_lines = ["# Netscape HTTP Cookie File\n", "# Extracted by export_cookies.py\n\n"]
    yt_names: set = set()
    skipped_empty = 0

    for host_key, name, value, path, expires_utc, is_secure in rows:
        if not RELEVANT_DOMAINS_RE.search(host_key):
            continue
        val = _decrypt_chrome_value(value)
        if val is None:
            skipped_empty += 1
            continue
        val = _escape_value(val)
        path = path or "/"
        expires = int(expires_utc or 0)
        secure = "TRUE" if is_secure else "FALSE"
        initial_dot = host_key.startswith(".")
        domain_specified = "TRUE" if initial_dot else "FALSE"
        if "youtube" in host_key.lower():
            yt_names.add(name)
        netscape_lines.append(
            f"{host_key}\t{domain_specified}\t{path}\t{secure}\t{expires}\t{name}\t{val}\n"
        )

    from tempfile import NamedTemporaryFile
    nt = NamedTemporaryFile(suffix=".txt", prefix="yt_chrome_cookies_", mode="w",
                            encoding="utf-8", delete=False)
    nt.writelines(netscape_lines)
    nt.close()
    netscape_tmp = nt.name

    missing = [n for n in IMPORTANT if n not in yt_names]
    return netscape_tmp, len(netscape_lines) - 2, missing


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


def _column_exists(conn, table: str, column: str) -> bool:
    try:
        conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
        return True
    except sqlite3.OperationalError:
        return False


def _decrypt_chrome_value(value) -> str | None:
    """Chrome/Edge SQLite 的 value 列通常是明文 text，直接返回"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


# 预编译正则：判断域名是否相关
import re as _re

RELEVANT_DOMAINS_RE = _re.compile(
    r"\.?(" + "|".join(d.replace(".", r"\.") for d in RELEVANT_DOMAINS) + r")$",
    _re.IGNORECASE,
)


def auto_extract_chrome_cookies(
    browser: str = "chrome",
) -> tuple[str, int, list[str], str]:
    """
    自动检测 Chrome 当前 Profile 并提取 Cookie。
    返回 (临时文件路径, cookie数量, 缺失关键cookie列表, 使用的Profile名)。
    优先读取 last_used Profile；被锁时降级读取最近可访问的 Profile。
    """
    import shutil, tempfile

    # 1. 检测 Profile
    info = detect_chrome_profile(browser)
    profile = info["profile"]
    email = info["email"]
    display_name = info["name"]
    print(f"🔍 检测到 Profile: {profile} ({email or display_name or '未知'})")

    # 2. 尝试读取该 Profile
    user_data_dir = (
        _get_edge_user_data_dir() if browser == "edge" else _get_chrome_user_data_dir()
    )
    cookie_db = os.path.join(user_data_dir, profile, "Network", "Cookies")

    # 3. 尝试直接复制（可能失败）
    try:
        shutil.copy2(cookie_db, tempfile.mktemp(suffix=".db"))
    except OSError:
        print(f"⚠️  {profile} Cookie 文件被锁定，降级搜索最近可访问的 Profile...")

        candidates = ["Default", "Profile 1", "Profile 3", "Profile 6"]
        for alt in candidates:
            if alt == profile:
                continue
            alt_db = os.path.join(user_data_dir, alt, "Network", "Cookies")
            if os.path.exists(alt_db):
                try:
                    shutil.copy2(alt_db, tempfile.mktemp(suffix=".db"))
                    profile = alt
                    alt_info = detect_chrome_profile(browser)
                    print(f"   → 降级使用: {alt} ({alt_info.get('email', '')})")
                    break
                except OSError:
                    continue
        else:
            raise OSError(
                "所有 Profile 的 Cookie 文件均被锁定（Chrome 正在运行）。"
                "请关闭 Chrome 后重试，或使用 --cookies 指定已导出的 cookie 文件。"
            )

    # 4. 提取并转换
    tmp_path, count, missing = extract_chrome_cookies_to_netscape(profile, browser)
    return tmp_path, count, missing, profile


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
            "  python export_cookies.py --chrome           # 自动检测 Chrome 当前 Profile\n"
            "  python export_cookies.py --chrome --output cookies.txt\n"
            "  python export_cookies.py --edge             # 自动检测 Edge 当前 Profile\n"
        )
    )
    parser.add_argument("--output", "-o", metavar="FILE",
                      help="指定输出文件（配合 --json / --chrome / --edge）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", "-j", metavar="FILE",
                      help="JSON 格式 Cookie（YouTube 官网导出）→ 转换为 Netscape 格式")
    group.add_argument("--verify", "-v", metavar="FILE",
                      help="验证 cookies.txt 是否完整")
    group.add_argument("--chrome", action="store_true",
                      help="从 Chrome 浏览器自动提取当前 Profile 的 Cookie（需关闭 Chrome）")
    group.add_argument("--edge", action="store_true",
                      help="从 Edge 浏览器自动提取当前 Profile 的 Cookie（需关闭 Edge）")
    args = parser.parse_args()

    if args.json:
        output = args.output or "cookies.txt"
        ok = convert_json_to_netscape(args.json, output)
        sys.exit(0 if ok else 1)

    if args.verify:
        ok = verify(args.verify)
        sys.exit(0 if ok else 1)

    if args.chrome or args.edge:
        browser = "edge" if args.edge else "chrome"
        try:
            tmp_path, count, missing, profile = auto_extract_chrome_cookies(browser)
            output = args.output or f"cookies_{browser}_{profile.replace(' ', '_')}.txt"
            import shutil
            shutil.copy2(tmp_path, output)
            os.unlink(tmp_path)
            print(f"\n✅ 已提取并保存: {os.path.abspath(output)} ({count} 个 Cookie)")
            for n in IMPORTANT:
                status = "✅" if n not in missing else "❌"
                print(f"   {status} {n}")
            if missing:
                print(f"\n⚠️  缺失关键 Cookie: {', '.join(missing)}")
                print("   可能原因：")
                print("   1. 浏览器中 YouTube 已退出登录 → 请重新在浏览器中登录 YouTube 后再提取")
                print("   2. 当前读取的是降级 Profile → 确认浏览器使用的是否为该 Profile")
                print("   3. Chrome 正在运行导致 Default 被锁 → 关闭 Chrome 后重新提取")
                print()
                print("   如无法解决，请使用 YouTube 官网导出 Cookie：")
                print("   python export_cookies.py --json cookies.json --output cookies.txt")
        except Exception as e:
            print(f"❌ 提取失败: {e}")
            sys.exit(1)
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()

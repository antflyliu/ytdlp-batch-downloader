"""
停止 B 机上的 Qwen3-ASR 服务
============================
通过 HTTP 探测 + 杀进程的简单实现(无 systemd 的 Windows 等价物)。

用法:
    python scripts/stop_server.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import urllib.request
import urllib.error


def _http_get(url: str, timeout: int = 3) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as e:
        return 0, {"error": str(e)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000, help="服务端口")
    p.add_argument("--dry-run", action="store_true", help="只列出,不杀")
    args = p.parse_args()

    code, body = _http_get(f"http://127.0.0.1:{args.port}/health")
    if code != 200:
        print(f"[INFO] /health 返回 {code} ({body.get('error') if body else 'no body'})")
        print("       服务可能已停止,继续清理进程 ...")

    # 找占用端口的 PID
    import subprocess
    out = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"],
        capture_output=True, text=True, shell=True,
    )
    pids: set[str] = set()
    needle = f":{args.port}"
    for line in out.stdout.splitlines():
        if needle in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                pids.add(parts[-1])
    if not pids:
        print(f"[INFO] 端口 {args.port} 没有任何 LISTENING 进程")
        return 0

    print(f"找到 {len(pids)} 个进程占用端口 {args.port}: {sorted(pids)}")
    if args.dry_run:
        return 0

    for pid in sorted(pids):
        # taskkill /F /PID
        rc = subprocess.run(
            ["taskkill", "/F", "/PID", pid],
            capture_output=True, text=True, shell=True,
        )
        print(f"  taskkill /F /PID {pid} -> {rc.returncode}")
        if rc.stdout:
            print(f"    {rc.stdout.strip()}")
    print("[OK] 已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

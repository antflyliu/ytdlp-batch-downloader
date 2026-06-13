"""
服务端健康检查 + 转写冒烟测试
============================
从 A 机(或其他机器)运行,验证 B 机服务是否可用。

用法:
    python scripts/healthcheck.py http://B机IP:8000
    python scripts/healthcheck.py http://192.168.1.20:8000 --api-key SECRET
    python scripts/healthcheck.py http://B机IP:8000 --audio test.wav
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import urllib.request
import urllib.error


def _http_get(url: str, headers: dict | None = None, timeout: int = 5) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def _http_post_multipart(
    url: str, file_path: Path, headers: dict, timeout: int = 120
) -> tuple[int, dict]:
    import email.mime.multipart
    import email.mime.application
    import uuid

    boundary = f"----qwen3asr{uuid.uuid4().hex}"
    body = bytearray()
    # file 字段
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode()
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    body += file_path.read_bytes()
    body += f"\r\n--{boundary}--\r\n".encode()
    headers = {**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"}
    req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8") or "{}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base", help="服务 base URL,例如 http://192.168.1.20:8000")
    p.add_argument("--api-key", default="")
    p.add_argument("--audio", help="可选:转写一个本地音频,跑端到端 smoke test")
    args = p.parse_args()

    base = args.base.rstrip("/")
    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    print(f"==> 探测 {base}/health")
    code, body = _http_get(urljoin(base + "/", "health"), headers=headers)
    print(f"   HTTP {code}  {body}")
    if code != 200:
        print("   [FAIL] /health 不通,服务未启动或被防火墙挡住")
        return 1

    print(f"==> 列出模型 {base}/v1/models")
    code, body = _http_get(urljoin(base + "/", "v1/models"), headers=headers)
    print(f"   HTTP {code}  {json.dumps(body, ensure_ascii=False)[:200]}")
    if code != 200 or not body.get("data"):
        print("   [FAIL] /v1/models 无模型")
        return 1

    if args.audio:
        path = Path(args.audio)
        if not path.exists():
            print(f"   [FAIL] 音频不存在: {path}")
            return 1
        print(f"==> 端到端转写 {path.name} ({(path.stat().st_size/1024/1024):.2f} MB)")
        t0 = time.time()
        code, body = _http_post_multipart(
            urljoin(base + "/", "v1/audio/transcriptions"),
            path, headers, timeout=600,
        )
        dt = time.time() - t0
        if code != 200:
            print(f"   [FAIL] HTTP {code}  {body}")
            return 1
        text = body.get("text", "")
        print(f"   HTTP {code}  耗时 {dt:.2f}s  长度 {len(text)} 字")
        print(f"   文本预览: {text[:200]}{'...' if len(text) > 200 else ''}")
    else:
        print("==> 跳过转写测试(没传 --audio)")

    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

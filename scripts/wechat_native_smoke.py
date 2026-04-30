from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


TERMINAL_TASK_STATUSES = {"done", "error", "cancelled"}


def _url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _request(
    method: str,
    base_url: str,
    path: str,
    *,
    api_token: str = "",
    payload: dict | None = None,
) -> tuple[int, bytes, str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    req = urllib.request.Request(_url(base_url, path), data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, body, exc.headers.get("Content-Type", "")


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    api_token: str = "",
    payload: dict | None = None,
) -> dict:
    status, body, _content_type = _request(method, base_url, path, api_token=api_token, payload=payload)
    try:
        parsed = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {path} returned non-JSON status={status}: {body[:200]!r}") from exc
    if status >= 400:
        raise RuntimeError(f"{method} {path} failed status={status}: {parsed}")
    return parsed


def _save_qrcode(base_url: str, api_token: str, login_id: str, output: Path) -> Path:
    status, body, content_type = _request(
        "GET",
        base_url,
        f"/api/wechat-native/login/{urllib.parse.quote(login_id)}/qrcode",
        api_token=api_token,
    )
    if status >= 400:
        raise RuntimeError(f"QR code request failed status={status}: {body[:200]!r}")
    suffix = ".png"
    if "jpeg" in content_type.lower() or "jpg" in content_type.lower():
        suffix = ".jpg"
    path = output.with_suffix(suffix)
    path.write_bytes(body)
    return path


def _poll_scan(base_url: str, api_token: str, login_id: str, timeout_seconds: int, interval_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        data = _request_json(
            "GET",
            base_url,
            f"/api/wechat-native/login/{urllib.parse.quote(login_id)}/scan",
            api_token=api_token,
        )
        print(f"scan status: {json.dumps(data, ensure_ascii=False)}")
        status = str(data.get("status") or data.get("code") or "")
        if status and status not in {"0", "pending", "waiting"}:
            return
        time.sleep(interval_seconds)


def _start_collection(args, session_id: str) -> None:
    payload = {
        "session_id": session_id,
        "format": args.format,
        "max_articles": args.max_articles,
        "delay_seconds": args.delay_seconds,
    }
    if args.output_dir:
        payload["output_dir"] = args.output_dir
    if args.fakeid:
        payload["fakeid"] = args.fakeid
        payload["source_mode"] = "fakeid"
    elif args.article_url:
        payload["article_url"] = args.article_url
        payload["source_mode"] = "url"
    else:
        print("No --fakeid or --article-url supplied; login smoke completed.")
        return

    preview = _request_json(
        "POST",
        args.base_url,
        "/api/wechat-native/articles/preview",
        api_token=args.api_token,
        payload={**payload, "limit": min(args.max_articles, 20)},
    )
    print(f"preview total: {preview.get('total')}")

    started = _request_json(
        "POST",
        args.base_url,
        "/api/wechat-native/tasks/start",
        api_token=args.api_token,
        payload=payload,
    )
    task_id = str(started.get("task_id") or "")
    print(f"task started: {task_id}")
    if not task_id:
        raise RuntimeError(f"task id missing: {started}")

    deadline = time.time() + args.task_timeout
    while time.time() < deadline:
        task = _request_json(
            "GET",
            args.base_url,
            f"/api/wechat-native/tasks/{urllib.parse.quote(task_id)}",
            api_token=args.api_token,
        )
        print(
            "task status: "
            f"{task.get('status')} completed={task.get('completed')} "
            f"success={task.get('success')} failed={task.get('failed')}"
        )
        if task.get("status") in TERMINAL_TASK_STATUSES:
            print(json.dumps(task, ensure_ascii=False, indent=2))
            return
        time.sleep(args.poll_interval)
    raise TimeoutError(f"task did not finish within {args.task_timeout}s: {task_id}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manual smoke test for the native WeChat MP login and collection API.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--api-token", default=os.environ.get("MONITOR_API_TOKEN", ""))
    parser.add_argument("--article-url", default="")
    parser.add_argument("--fakeid", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--format", default="markdown", choices=["html", "markdown", "text", "json"])
    parser.add_argument("--max-articles", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--login-timeout", type=int, default=180)
    parser.add_argument("--task-timeout", type=int, default=240)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--qrcode-output", default="wechat-native-login-qrcode.png")
    parser.add_argument("--skip-poll", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.max_articles < 1:
        raise ValueError("--max-articles must be >= 1")

    started = _request_json("POST", args.base_url, "/api/wechat-native/login/start", api_token=args.api_token, payload={})
    login_id = str(started.get("login_id") or "")
    if not login_id:
        raise RuntimeError(f"login_id missing: {started}")

    qr_path = _save_qrcode(args.base_url, args.api_token, login_id, Path(args.qrcode_output))
    print(f"QR code saved: {qr_path.resolve()}")
    print("Scan the QR code in WeChat MP and approve login on the phone.")
    if not args.skip_poll:
        _poll_scan(args.base_url, args.api_token, login_id, args.login_timeout, args.poll_interval)

    input("Press Enter after scan approval to confirm login...")
    confirmed = _request_json(
        "POST",
        args.base_url,
        f"/api/wechat-native/login/{urllib.parse.quote(login_id)}/confirm",
        api_token=args.api_token,
        payload={},
    )
    session_id = str(confirmed.get("session_id") or "")
    if not session_id:
        raise RuntimeError(f"session_id missing: {confirmed}")
    print(f"session confirmed: {session_id}")

    checked = _request_json(
        "POST",
        args.base_url,
        f"/api/wechat-native/sessions/{urllib.parse.quote(session_id)}/check",
        api_token=args.api_token,
        payload={},
    )
    print(f"session check: {json.dumps(checked, ensure_ascii=False)}")

    _start_collection(args, session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

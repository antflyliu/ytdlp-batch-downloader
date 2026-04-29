"""
MCP Server — 零依赖 stdio 实现
Wraps scripts/cli.py as an MCP server (Model Context Protocol, stdio transport).

OpenClaw 配置示例:
{
  "mcpServers": {
    "ytdlp-downloader": {
      "command": "python",
      "args": ["mcp-server/server.py"],
      "cwd": "D:\\WORKSPACE\\video-download-space\\ytdlp-batch-downloader",
      "transportType": "stdio"
    }
  }
}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

# ── 路径配置 ───────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent.resolve()
_CLI = _ROOT / "scripts" / "cli.py"
sys.path.insert(0, str(_ROOT))


# ── MCP 协议常量 ────────────────────────────────────────────────────────────
MCP_VERSION = "2024-11-05"

# ── MCP JSON-RPC helpers ────────────────────────────────────────────────────

def msg_id() -> int:
    return id(threading.current_thread()) ^ os.getpid()


def resp(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def ok_result(content: list[dict]) -> str:
    return resp({
        "jsonrpc": "2.0",
        "id": msg_id(),
        "result": {"content": content}
    })


def ok_result_structured(data: Any, is_error: bool = False) -> str:
    return resp({
        "jsonrpc": "2.0",
        "id": msg_id(),
        "result": {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
            "isError": is_error,
            "structuredContent": data,
        }
    })


def err(code: int, msg: str) -> str:
    return resp({
        "jsonrpc": "2.0",
        "id": msg_id(),
        "error": {"code": code, "message": msg}
    })


def progress(content: list[dict]) -> str:
    return resp({
        "jsonrpc": "2.0",
        "result": {"content": content, "progress": {}}
    })


# ── CLI 执行器 ──────────────────────────────────────────────────────────────

def run_cli(args: list[str], timeout: int = 300) -> dict:
    """执行 scripts/cli.py，返回 (returncode, stdout, stderr)。"""
    cmd = [sys.executable, str(_CLI)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_ROOT),
            env=os.environ.copy(),
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "ok": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "TIMEOUT", "ok": False}
    except Exception as e:
        return {"returncode": -2, "stdout": "", "stderr": str(e), "ok": False}


# ── 工具定义 ────────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "deps",
        "description": "检查 yt-dlp / aria2c / ffmpeg / whisperx 依赖是否就绪。返回各工具的可用性和版本。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "check_url",
        "description": "检测单个 URL 是否可下载，返回视频标题、时长、作者等信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "视频 URL",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "download",
        "description": "批量下载视频。委托给 Youtube_Downloader.batch_download。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "URL 文件路径 (.xlsx/.txt/.csv) 或逗号分隔的 URL",
                },
                "output": {
                    "type": "string",
                    "description": "下载目录 (默认: videos)",
                    "default": "videos",
                },
                "resolution": {
                    "type": "string",
                    "description": "视频分辨率",
                    "enum": ["720p", "1080p", "1440p"],
                    "default": "1080p",
                },
                "proxy": {
                    "type": "string",
                    "description": "代理地址 (如: http://127.0.0.1:7890)",
                },
                "no_subs": {
                    "type": "boolean",
                    "description": "是否下载字幕",
                    "default": False,
                },
                "max": {
                    "type": "integer",
                    "description": "最多下载数量",
                },
            },
            "required": ["input"],
        },
    },
    {
        "name": "monitor",
        "description": "YouTube 频道监控子命令: start / stop / once / list / add / enable / disable / delete",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "monitor 子命令",
                    "enum": ["start", "stop", "once", "list", "reload"],
                },
                "args": {
                    "type": "string",
                    "description": "额外参数 (JSON 字符串或空格分隔)",
                },
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "stats",
        "description": "显示监控账户统计：扫描次数、新视频数、最后扫描时间。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "events",
        "description": "显示最近扫描事件记录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "显示数量 (默认 20)",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "list_accounts",
        "description": "列出所有已配置的监控账户。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "quota",
        "description": "查询 YouTube Data API Quota 使用情况。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_key_env": {
                    "type": "string",
                    "description": "API Key 环境变量名 (不填则显示所有)",
                },
            },
        },
    },
]


# ── 工具调用路由 ────────────────────────────────────────────────────────────

def call_tool(name: str, arguments: dict) -> str:
    """根据工具名路由到对应的 CLI 调用。"""
    try:
        match name:
            case "deps":
                result = run_cli(["deps", "--json"], timeout=30)
                if result["ok"]:
                    return ok_result_structured(json.loads(result["stdout"]))
                return ok_result_structured({"error": result["stderr"]}, is_error=True)

            case "check_url":
                url = arguments.get("url", "")
                if not url:
                    return ok_result_structured({"error": "url is required"}, is_error=True)
                result = run_cli(["check-url", url, "--json"], timeout=30)
                if result["ok"]:
                    return ok_result_structured(json.loads(result["stdout"]))
                return ok_result_structured({"error": result["stderr"]}, is_error=True)

            case "download":
                args = ["download", "--json", "-i", arguments.get("input", "")]
                out = arguments.get("output")
                if out:
                    args += ["-o", out]
                res = arguments.get("resolution")
                if res:
                    args += ["-r", res]
                proxy = arguments.get("proxy")
                if proxy:
                    args += ["-p", proxy]
                if arguments.get("no_subs"):
                    args.append("--no-subs")
                max_n = arguments.get("max")
                if max_n:
                    args += ["-n", str(max_n)]
                result = run_cli(args, timeout=7200)
                if result["ok"]:
                    try:
                        data = json.loads(result["stdout"])
                    except Exception:
                        data = {"stdout": result["stdout"]}
                    return ok_result_structured(data)
                return ok_result_structured({"error": result["stderr"], "stdout": result["stdout"]}, is_error=True)

            case "monitor":
                cmd = arguments.get("cmd", "list")
                extra = arguments.get("args", "")
                args_list = extra.split() if extra else []
                result = run_cli(["monitor", cmd] + args_list, timeout=60)
                return ok_result_structured({
                    "cmd": cmd,
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "returncode": result["returncode"],
                }, is_error=not result["ok"])

            case "stats":
                result = run_cli(["stats", "--json"], timeout=15)
                if result["ok"]:
                    return ok_result_structured(json.loads(result["stdout"]))
                return ok_result_structured({"error": result["stderr"]}, is_error=True)

            case "events":
                limit = arguments.get("limit", 20)
                result = run_cli(["events", "--json", "--limit", str(limit)], timeout=15)
                if result["ok"]:
                    return ok_result_structured(json.loads(result["stdout"]))
                return ok_result_structured({"error": result["stderr"]}, is_error=True)

            case "list_accounts":
                result = run_cli(["list", "--json"], timeout=15)
                if result["ok"]:
                    return ok_result_structured(json.loads(result["stdout"]))
                return ok_result_structured({"error": result["stderr"]}, is_error=True)

            case "quota":
                api_key = arguments.get("api_key_env")
                args_list = ["quota", "--json"]
                if api_key:
                    args_list += ["--api-key", api_key]
                result = run_cli(args_list, timeout=15)
                if result["ok"]:
                    return ok_result_structured(json.loads(result["stdout"]))
                return ok_result_structured({"error": result["stderr"]}, is_error=True)

            case _:
                return ok_result_structured({"error": f"Unknown tool: {name}"}, is_error=True)
    except Exception as e:
        return ok_result_structured({"error": str(e)}, is_error=True)


# ── MCP stdio 协议主循环 ────────────────────────────────────────────────────

def main() -> None:
    """MCP stdio 主循环：读 stdin → 解析 JSON-RPC → 处理 → 写 stdout。"""
    initialize_done = False

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {})

        # ── 初始化 ────────────────────────────────────────────────────────
        if method == "initialize":
            initialize_done = True
            print(resp({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_VERSION,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "ytdlp-mcp-server",
                        "version": "1.0.0",
                    },
                }
            }), flush=True)
            continue

        # 初始化前不响应其他请求
        if not initialize_done:
            continue

        # ── 工具列表 ──────────────────────────────────────────────────────
        if method == "tools/list":
            print(resp({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS},
            }), flush=True)
            continue

        # ── 工具调用 ───────────────────────────────────────────────────────
        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            print(call_tool(name, arguments), flush=True)
            continue

        # ── 其他方法（ping / notifications 等） ─────────────────────────
        if method == "ping":
            print(resp({"jsonrpc": "2.0", "id": req_id, "result": {}}), flush=True)
            continue

        # unknown method → silent skip


if __name__ == "__main__":
    main()

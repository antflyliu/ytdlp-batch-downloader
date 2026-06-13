# Qwen3-ASR B 机部署包

本目录是 **远程 B 机(6GB 显存那台)** 的一键部署脚本集合。
模型选 **Qwen3-ASR-0.6B**(1.7B 装不下 6GB)。

## 目录结构

```
deploy/qwen3-asr/
├── README.md                # 本文件
├── scripts/
│   ├── check_env.py         # 环境自检(零依赖,纯标准库)
│   ├── install.bat          # 一键安装:venv + torch(CU129) + qwen-asr[vllm] + 模型
│   ├── start_server.bat     # 启动 OpenAI 兼容服务(默认 vLLM 后端,fallback transformers)
│   ├── open_firewall.bat    # 放行 8000 端口(需管理员)
│   ├── healthcheck.py       # 跨机健康检查 + 端到端转写 smoke test
│   ├── stop_server.py       # 停服务(taskkill 占用端口的进程)
│   └── serve_transformers.py# vLLM 安装失败时的备用 server
├── models/                  # 模型权重(脚本自动下载到这里)
└── logs/                    # 安装/运行日志
```

## 部署流程(B 机)

| 步骤 | 命令 | 备注 |
|---|---|---|
| 1. 把本目录拷到 B 机 | `scp -r deploy/qwen3-asr user@B:/path/` | 任何方式都行 |
| 2. 自检 | `python scripts/check_env.py` | 不装任何东西 |
| 3. 安装 | `scripts\install.bat` | 需 10-25 分钟,带日志 |
| 4. 放行端口 | **管理员身份**运行 `scripts\open_firewall.bat` | 仅首次 |
| 5. 启动服务 | `scripts\start_server.bat` | 默认监听 0.0.0.0:8000 |
| 6. (A 机)验证 | `python scripts/healthcheck.py http://B机IP:8000` | 见下 |

## 服务可调参数(环境变量)

```bat
set PORT=8000                REM 监听端口
set HOST=0.0.0.0             REM 监听地址(0.0.0.0 = 接受远程)
set MODEL=Qwen/Qwen3-ASR-0.6B
set GPU_MEM_UTIL=0.85        REM 显存利用率上限,留 15% 给系统
set API_KEY=YOUR_SECRET      REM 留空 = 不鉴权(仅 LAN 推荐)
set BACKEND=vllm             REM 或 transformers
scripts\start_server.bat
```

## A 机(本机)客户端调用

**OpenAI 兼容 SDK**(推荐):
```python
from openai import OpenAI
client = OpenAI(
    base_url="http://B机IP:8000/v1",
    api_key="YOUR_SECRET",   # 没设 token 传空字符串
)
result = client.audio.transcriptions.create(
    file=open("audio.wav", "rb"),
    model="qwen3-asr",
)
print(result.text)
```

**纯标准库 curl**:
```bash
curl -X POST http://B机IP:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer YOUR_SECRET" \
  -F file=@audio.wav
```

## 监控

```bash
# 实时看日志
type logs\server_*.log | findstr /v "INFO" 2>nul   # 简洁版
# 或直接打开 logs\ 下最新文件
```

## 常见问题

| 现象 | 排查 |
|---|---|
| 启动 OOM | `GPU_MEM_UTIL=0.7` 重试;或换 `BACKEND=transformers` |
| A 机连不上 | 防火墙 / 路由 / 端口;先在 B 机 `curl 127.0.0.1:8000/health` 验证 |
| 模型下载慢 | 切 ModelScope:`set HF_ENDPOINT=https://hf-mirror.com` 或走代理 |
| 1.7B 跑不了 | 6GB 显存装不下 1.7B,坚持 0.6B,或换 ≥10GB 显存的卡 |
| vLLM 安装失败 | install.bat 已自动 fallback 到 transformers,功能一致,只是慢 |

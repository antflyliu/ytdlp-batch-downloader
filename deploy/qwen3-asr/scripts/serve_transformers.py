"""
transformers 后端的 OpenAI 兼容 ASR server
=========================================
当 vLLM 安装失败时,使用此脚本启动 transformers 后端,
对外暴露 OpenAI 兼容的 /v1/audio/transcriptions 端点。

启动方式:
    python scripts/serve_transformers.py \\
        --model Qwen/Qwen3-ASR-0.6B \\
        --host 0.0.0.0 --port 8000 \\
        --api-key YOUR_SECRET
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Optional

from flask import Flask, jsonify, request  # type: ignore


def _build_app(model_path: str, api_key: str) -> Flask:
    import torch
    from qwen_asr import QwenASR  # type: ignore

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    log = logging.getLogger("qwen3-asr-serve")

    log.info("加载模型 %s ...", model_path)
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    asr = QwenASR(
        model=model_path,
        dtype=dtype,
        device_map=device,
    )
    log.info("模型加载完成 (device=%s, dtype=%s)", device, dtype)

    app = Flask(__name__)

    def _check_auth() -> Optional[tuple]:
        if not api_key:
            return None
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {api_key}":
            return None
        return jsonify({"error": "unauthorized"}), 401

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "model": model_path, "device": device})

    @app.get("/v1/models")
    def list_models():
        return jsonify({
            "object": "list",
            "data": [{
                "id": "qwen3-asr",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "qwen",
            }],
        })

    @app.post("/v1/audio/transcriptions")
    def transcribe():
        denied = _check_auth()
        if denied is not None:
            return denied
        if "file" not in request.files:
            return jsonify({"error": "missing 'file' field"}), 400
        f = request.files["file"]
        tmp_path = f"/tmp/_asr_{int(time.time()*1000)}_{f.filename}"
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        f.save(tmp_path)
        try:
            log.info("转写: %s (%.1f MB)", f.filename,
                     os.path.getsize(tmp_path) / 1024 / 1024)
            t0 = time.time()
            results = asr.transcribe(
                audio=[tmp_path],
                language=None,  # 自动语种识别
            )
            elapsed = time.time() - t0
            text = "\n".join(r.text for r in results) if results else ""
            log.info("完成 耗时 %.2fs 长度 %d 字", elapsed, len(text))
            return jsonify({"text": text, "language": getattr(results[0], "language", None) if results else None})
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return app


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--api-key", default="")
    args = p.parse_args()

    app = _build_app(args.model, args.api_key)
    # 关闭 reloader,避免模型被加载两次
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

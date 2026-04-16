#!/usr/bin/env python3
"""
scripts/video_clipper.py — AI 视频切片 CLI 入口

用法:
    # 完整流程（视频 + 字幕 → AI分析 → 切片）
    python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips

    # 跳过已有步骤（断点续跑）
    python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips --skip step5_clustering --skip step6_video

    # 指定 LLM 后端
    python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips --provider qwen --model qwen-plus
    python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips --provider openai --model gpt-4o
    python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips --provider ollama --model llama3

    # 调整参数
    python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips --min-score 8.0 --chunk-minutes 20

    # 列出支持的 LLM 后端
    python scripts/video_clipper.py --list-providers
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# 项目路径
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _check_ffmpeg() -> bool:
    try:
        import subprocess
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _check_whisperx() -> bool:
    try:
        import whisperx  # noqa: F401
        return True
    except ImportError:
        return False


def cmd_deps() -> int:
    """检查依赖是否安装"""
    print("检查依赖...")
    deps = [
        ("ffmpeg", _check_ffmpeg(), "视频切割与编码"),
        ("whisperx", _check_whisperx(), "字幕生成（可选）"),
    ]

    all_ok = True
    for name, ok, desc in deps:
        status = "✅ 已安装" if ok else "❌ 未安装"
        print(f"  {name}: {status} — {desc}")
        if not ok:
            all_ok = False

    # LLM 后端检查
    from scripts.llm_client import LLMClient
    providers = LLMClient.list_providers()
    print(f"\n支持的 LLM 后端 ({len(providers)}): {', '.join(providers)}")
    print("配置环境变量: LLM_PROVIDER / LLM_API_KEY / LLM_MODEL / LLM_BASE_URL")
    return 0 if all_ok else 1


def cmd_clip(
    video_path: str,
    srt_path: str,
    output_dir: str,
    provider: str,
    model: str | None,
    min_score: float,
    chunk_minutes: float,
    skip_steps: list[str],
    verbose: bool,
    notify: str | None = None,
    notify_webhook: str | None = None,
    notify_title: str | None = None,
) -> int:
    """运行切片 Pipeline"""
    from scripts.llm_client import create_llm_client
    from scripts.clip_pipeline import ClipPipeline

    _setup_logging(verbose)
    logger = logging.getLogger("video_clipper")

    # 创建 LLM 客户端
    llm_client = create_llm_client(provider=provider, model=model)
    logger.info(f"LLM 后端: {provider}, 模型: {model or llm_client.model}")

    # 初始化 Pipeline
    pipeline = ClipPipeline(
        llm_client=llm_client,
        output_dir=output_dir,
        min_score=min_score,
        chunk_minutes=chunk_minutes,
    )

    # 运行
    try:
        ctx = pipeline.run(
            video_path=video_path,
            srt_path=srt_path,
            skip_steps=skip_steps or [],
        )
        # 输出摘要
        print("\n" + "=" * 60)
        print("切片完成!")
        print(f"  输出目录: {ctx.output_dir}")
        print(f"  高分切片: {len(ctx.high_score_clips)} 个")
        print(f"  生成视频: {len(ctx.generated_clips)} 个")
        print(f"  合集: {len(ctx.generated_collections)} 个")
        print("=" * 60)

        # 列出生成的文件
        clips_dir = ctx.output_dir / "clips"
        if clips_dir.exists():
            clips = sorted(clips_dir.glob("*.mp4"))
            print(f"\n切片文件 ({len(clips)}):")
            for c in clips:
                print(f"  {c.name}")

        coll_dir = ctx.output_dir / "collections"
        if coll_dir.exists():
            colls = sorted(coll_dir.glob("*.mp4"))
            print(f"\n合集文件 ({len(colls)}):")
            for c in colls:
                print(f"  {c.name}")

        # 发送通知
        if notify:
            video_title = (
                notify_title
                or Path(video_path).stem
                or None
            )
            try:
                from scripts.clip_notifier import notify_pipeline_result
                result = notify_pipeline_result(
                    ctx,
                    platform=notify,  # type: ignore
                    webhook_url=notify_webhook,
                    video_title=video_title,
                )
                for plat, (ok, msg) in result.items():
                    status = "✅" if ok else "❌"
                    print(f"\n{status} 通知 [{plat}]: {msg}")
            except Exception as e:
                logger.warning(f"通知发送失败: {e}")

        return 0
    except Exception as e:
        logger.exception(f"Pipeline 执行失败: {e}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="video_clipper",
        description="AI 视频高光切片工具 — 基于 LLM 的智能视频切片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/video_clipper.py -i video.mp4 -s video.srt -o output/clips
  python scripts/video_clipper.py -i video.mp4 -s video.srt --provider openai --model gpt-4o
  python scripts/video_clipper.py --deps
        """,
    )

    # 依赖检查
    parser.add_argument("--deps", action="store_true", help="检查系统依赖")
    parser.add_argument("--list-providers", action="store_true", help="列出支持的 LLM 后端")

    # 主流程参数
    parser.add_argument("-i", "--video", dest="video_path", help="视频文件路径")
    parser.add_argument("-s", "--srt", dest="srt_path", help="字幕文件路径 (.srt)")
    parser.add_argument("-o", "--output", dest="output_dir", default="output/clips", help="输出目录 (默认: output/clips)")

    # LLM 参数
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "qwen"),
                        choices=["qwen", "openai", "ollama", "groq"],
                        help="LLM 后端 (默认: qwen)")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL"),
                        help="LLM 模型名称 (默认: 各后端内置默认)")
    parser.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"),
                        help="API Key (默认: 环境变量 LLM_API_KEY)")

    # 切片参数
    parser.add_argument("--min-score", type=float, default=7.0,
                        help="最低精彩评分阈值 (默认: 7.0, 范围 0-10)")
    parser.add_argument("--chunk-minutes", type=float, default=30.0,
                        help="每块最大时长(分钟) (默认: 30)")
    parser.add_argument("--skip", dest="skip_steps", action="append", default=[],
                        help="跳过的 Pipeline 步骤 (如 --skip step5_clustering)")

    # 通用
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")

    # 通知参数
    parser.add_argument(
        "--notify", choices=["feishu", "dingtalk", "wecom", "telegram"],
        help="Pipeline 完成后自动发送通知到指定平台（自动从全局配置读取 Webhook URL）"
    )
    parser.add_argument(
        "--notify-webhook",
        help="指定通知 Webhook URL（覆盖全局配置）"
    )
    parser.add_argument(
        "--notify-title",
        help="通知中显示的视频标题（默认从文件名提取）"
    )

    args = parser.parse_args()

    # 依赖检查
    if args.deps:
        return cmd_deps()

    # 列出后端
    if args.list_providers:
        from scripts.llm_client import LLMClient
        providers = LLMClient.list_providers()
        print("支持的 LLM 后端:")
        for p in providers:
            print(f"  - {p}")
        return 0

    # 参数校验
    if not args.video_path or not args.srt_path:
        parser.print_help()
        print("\n错误: 必须指定 -i/--video 和 -s/--srt")
        return 1

    if not Path(args.video_path).exists():
        print(f"错误: 视频文件不存在: {args.video_path}")
        return 1
    if not Path(args.srt_path).exists():
        print(f"错误: SRT 文件不存在: {args.srt_path}")
        return 1

    return cmd_clip(
        video_path=args.video_path,
        srt_path=args.srt_path,
        output_dir=args.output_dir,
        provider=args.provider,
        model=args.model,
        min_score=args.min_score,
        chunk_minutes=args.chunk_minutes,
        skip_steps=args.skip_steps,
        verbose=args.verbose,
        notify=args.notify,
        notify_webhook=args.notify_webhook,
        notify_title=args.notify_title,
    )


if __name__ == "__main__":
    sys.exit(main())

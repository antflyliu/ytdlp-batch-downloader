#!/usr/bin/env python3
"""
scripts/clip_pipeline.py — 6 步 AI 视频切片 Pipeline 编排器

Pipeline 步骤:
  Step1: 大纲提取   ← SRT 分块 → LLM 提取视频话题大纲
  Step2: 时间线提取 ← 大纲 + 原文本 → LLM 识别每个话题的 start/end 时间
  Step3: 精彩评分   ← 时间线数据 → LLM 批量评分 → 过滤低分片段
  Step4: 标题生成   ← 高分片段 → LLM 生成吸引人的标题
  Step5: 主题聚类   ← 所有切片 → LLM 主题聚类 → 推荐视频合集
  Step6: 视频生成   ← ffmpeg 切割片段 + 合集拼接

每个步骤的中间结果保存到 JSON 文件，可单独重跑。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, List, Optional

from .llm_client import LLMClient, create_llm_client
from .text_processor import (
    SRTEntry,
    chunk_srt_data,
    parse_subtitles,
    save_chunks,
)
from .video_processor import VideoProcessor

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MIN_SCORE = 7.0          # 最低评分阈值
DEFAULT_CHUNK_MINUTES = 30       # 分块时长（分钟）
DEFAULT_CHUNK_CHARS = 4000       # 每块最大字符数

# Prompt 文件名（相对于本模块所在目录）
_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """加载 prompt 模板文件"""
    path = _PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Context — 携带所有中间状态
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineContext:
    """Pipeline 执行上下文，保存每步的中间结果"""
    video_path: Path
    srt_path: Path
    output_dir: Path
    category: str = "knowledge"          # 分类场景（knowledge/speech/entertainment）
    chunk_minutes: float = DEFAULT_CHUNK_MINUTES
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    min_score: float = DEFAULT_MIN_SCORE
    llm_client: Optional[LLMClient] = None

    # ── 中间结果 ────────────────────────────────────────────────────────────
    srt_entries: List[SRTEntry] = None       # 原始字幕条目
    chunks: List[dict] = None                  # 分块结果
    outlines: List[dict] = None                # Step1: 大纲
    timeline: List[dict] = None                # Step2: 时间线
    scored_clips: List[dict] = None            # Step3: 评分后的片段
    high_score_clips: List[dict] = None        # Step3: 高分片段
    clips_with_titles: List[dict] = None      # Step4: 带标题的片段
    collections: List[dict] = None            # Step5: 合集
    generated_clips: List[dict] = None        # Step6: 生成的切片视频
    generated_collections: List[dict] = None # Step6: 生成的合集视频

    def __post_init__(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.srt_entries = []
        self.chunks = []
        self.outlines = []
        self.timeline = []
        self.scored_clips = []
        self.high_score_clips = []
        self.clips_with_titles = []
        self.collections = []
        self.generated_clips = []
        self.generated_collections = []

    def save_json(self, name: str, data: Any) -> Path:
        """保存 JSON 到 output_dir，返回路径"""
        path = self.output_dir / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"保存: {path}")
        return path

    def load_json(self, name: str) -> Any:
        """从 output_dir 加载 JSON，不存在返回 None"""
        path = self.output_dir / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None



# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Steps
# ─────────────────────────────────────────────────────────────────────────────

class PipelineStep:
    """Pipeline 单步基类"""

    name: str = ""

    def run(self, ctx: PipelineContext) -> None:
        raise NotImplementedError


class Step1Outline(PipelineStep):
    """Step1: 大纲提取"""

    name = "step1_outline"

    def run(self, ctx: PipelineContext) -> None:
        logger.info("=" * 60)
        logger.info("Step1: 大纲提取")
        logger.info("=" * 60)

        # 解析 SRT
        ctx.srt_entries = parse_subtitles(ctx.srt_path)
        if not ctx.srt_entries:
            raise RuntimeError("SRT 文件为空或解析失败")

        # 分块
        ctx.chunks = chunk_srt_data(
            ctx.srt_entries,
            interval_minutes=ctx.chunk_minutes,
            max_chars_per_chunk=ctx.chunk_chars,
        )
        save_chunks(ctx.chunks, ctx.output_dir / "step1_chunks")
        logger.info(f"分块完成: {len(ctx.chunks)} 个块")

        # 检查总内容是否过少
        total_chars = sum(len(c["text"]) for c in ctx.chunks)
        logger.info(f"总字幕字符数: {total_chars}")
        if total_chars < 30:
            logger.warning(f"字幕内容过少（{total_chars} 字），跳过大纲提取")
            ctx.outlines = []
            ctx.save_json("step1_outline", ctx.outlines)
            return

        # 每块调用 LLM
        outline_prompt = _load_prompt("outline")
        all_outlines = []

        for chunk in ctx.chunks:
            chunk_text = chunk["text"].strip()
            if len(chunk_text) < 20:
                logger.info(f"块 {chunk['chunk_index']} 内容过少（{len(chunk_text)} 字），跳过")
                continue
            response = ctx.llm_client.call_with_retry(outline_prompt, chunk_text, max_tokens=2000)
            if not response:
                logger.warning(f"块 {chunk['chunk_index']} LLM 返回为空，跳过")
                continue
            try:
                parsed = ctx.llm_client.parse_json_response(response)
                # 附加 chunk_index 以便后续映射
                for item in parsed:
                    item["chunk_index"] = chunk["chunk_index"]
                all_outlines.extend(parsed)
            except Exception as e:
                logger.warning(f"块 {chunk['chunk_index']} 解析失败: {e}")

        # 去重（按 title）
        seen = set()
        unique = []
        for o in all_outlines:
            t = o.get("title", "")
            if t and t not in seen:
                seen.add(t)
                unique.append(o)
        ctx.outlines = unique
        ctx.save_json("step1_outline", ctx.outlines)
        logger.info(f"大纲提取完成: {len(ctx.outlines)} 个话题")


class Step2Timeline(PipelineStep):
    """Step2: 时间线提取 — 为每个大纲话题确定精确时间"""

    name = "step2_timeline"

    def run(self, ctx: PipelineContext) -> None:
        logger.info("=" * 60)
        logger.info("Step2: 时间线提取")
        logger.info("=" * 60)

        if not ctx.outlines:
            logger.warning("无大纲内容，跳过 Step2")
            ctx.timeline = []
            ctx.save_json("step2_timeline", ctx.timeline)
            return

        # 构建上下文：每个大纲话题 + 所属块的原文
        topic_context = []
        for outline in ctx.outlines:
            ci = outline.get("chunk_index", 0)
            chunk = next((c for c in ctx.chunks if c["chunk_index"] == ci), None)
            content = chunk["text"] if chunk else ""
            topic_context.append({
                "outline": outline["title"],
                "subtopics": outline.get("subtopics", []),
                "content_hint": content[:500],
            })

        timeline_prompt = _load_prompt("timeline")
        response = ctx.llm_client.call_with_retry(timeline_prompt, topic_context)
        if not response:
            raise RuntimeError("Step2 LLM 调用失败")

        parsed = ctx.llm_client.parse_json_response(response)

        # 为每个 timeline 附加原始 outline 和 chunk_index
        for tl, outline in zip(parsed, ctx.outlines):
            tl["outline"] = outline
            tl["chunk_index"] = outline.get("chunk_index", 0)

        # 分配固定 ID
        for i, tl in enumerate(parsed):
            tl["id"] = i

        ctx.timeline = parsed
        ctx.save_json("step2_timeline", ctx.timeline)
        logger.info(f"时间线提取完成: {len(ctx.timeline)} 个时间段")


class Step3Scoring(PipelineStep):
    """Step3: 精彩评分 + 过滤"""

    name = "step3_scoring"

    def run(self, ctx: PipelineContext) -> None:
        logger.info("=" * 60)
        logger.info("Step3: 精彩评分")
        logger.info("=" * 60)

        scoring_prompt = _load_prompt("scoring")

        # 按 chunk_index 分组，批量处理
        from collections import defaultdict
        by_chunk = defaultdict(list)
        for tl in ctx.timeline:
            by_chunk[tl.get("chunk_index", 0)].append(tl)

        all_scored = []
        for ci, items in by_chunk.items():
            response = ctx.llm_client.call_with_retry(scoring_prompt, items)
            if not response:
                logger.warning(f"块 {ci} 评分失败")
                for item in items:
                    item["final_score"] = 0.0
                    item["recommend_reason"] = "评分失败"
                all_scored.extend(items)
                continue
            try:
                parsed = ctx.llm_client.parse_json_response(response)
                for orig, scored in zip(items, parsed):
                    orig["final_score"] = float(scored.get("final_score", 0))
                    orig["recommend_reason"] = scored.get("recommend_reason", "")
                all_scored.extend(items)
            except Exception as e:
                logger.warning(f"块 {ci} 解析失败: {e}")
                for item in items:
                    item["final_score"] = 0.0
                    item["recommend_reason"] = "解析失败"
                all_scored.extend(items)

        # 按评分降序，再按 ID 升序（保持时间顺序）
        all_scored.sort(key=lambda x: (-x.get("final_score", 0), x.get("id", 0)))

        ctx.scored_clips = all_scored
        ctx.save_json("step3_all_scored", ctx.scored_clips)

        # 过滤高分
        ctx.high_score_clips = [c for c in all_scored if c.get("final_score", 0) >= ctx.min_score]
        ctx.save_json("step3_high_score_clips", ctx.high_score_clips)
        logger.info(f"评分完成: {len(ctx.scored_clips)} 个片段, {len(ctx.high_score_clips)} 个高分")


class Step4Title(PipelineStep):
    """Step4: 为高分片段生成标题"""

    name = "step4_title"

    def run(self, ctx: PipelineContext) -> None:
        logger.info("=" * 60)
        logger.info("Step4: 标题生成")
        logger.info("=" * 60)

        if not ctx.high_score_clips:
            logger.warning("无高分片段，跳过 Step4")
            ctx.clips_with_titles = []
            return

        title_prompt = _load_prompt("title")
        response = ctx.llm_client.call_with_retry(title_prompt, ctx.high_score_clips)
        if not response:
            raise RuntimeError("Step4 LLM 调用失败")

        parsed = ctx.llm_client.parse_json_response(response)

        # 合并标题到原始片段
        for clip, title_data in zip(ctx.high_score_clips, parsed):
            clip["generated_title"] = title_data.get("generated_title", clip.get("outline", ""))
            clip["title_style"] = title_data.get("title_style", "")

        ctx.clips_with_titles = ctx.high_score_clips
        ctx.save_json("step4_clips_with_titles", ctx.clips_with_titles)
        logger.info(f"标题生成完成: {len(ctx.clips_with_titles)} 个切片")


class Step5Clustering(PipelineStep):
    """Step5: 主题聚类，生成合集推荐"""

    name = "step5_clustering"

    def run(self, ctx: PipelineContext) -> None:
        logger.info("=" * 60)
        logger.info("Step5: 主题聚类与合集推荐")
        logger.info("=" * 60)

        if not ctx.clips_with_titles:
            logger.warning("无切片，跳过 Step5")
            ctx.collections = []
            return

        clustering_prompt = _load_prompt("clustering")
        response = ctx.llm_client.call_with_retry(clustering_prompt, ctx.clips_with_titles)
        if not response:
            logger.warning("Step5 LLM 调用失败，合集跳过")
            ctx.collections = []
            return

        parsed = ctx.llm_client.parse_json_response(response)

        # 构建完整合集数据（附带切片详情）
        collections = []
        for i, coll in enumerate(parsed):
            indices = coll.get("outline_indices", [])
            clip_paths = [
                str(ctx.output_dir / "clips" / f"clip_{ctx.clips_with_titles[idx]['id']:04d}.mp4")
                for idx in indices
                if idx < len(ctx.clips_with_titles)
            ]
            collections.append({
                "id": i,
                "title": coll.get("collection_title", f"合集_{i}"),
                "description": coll.get("collection_description", ""),
                "outline_indices": indices,
                "clip_ids": [ctx.clips_with_titles[idx]["id"] for idx in indices if idx < len(ctx.clips_with_titles)],
                "clip_paths": clip_paths,
            })

        ctx.collections = collections
        ctx.save_json("step5_collections", ctx.collections)
        logger.info(f"主题聚类完成: {len(ctx.collections)} 个合集")


class Step6Video(PipelineStep):
    """Step6: ffmpeg 切割 + 合集拼接"""

    name = "step6_video"

    def run(self, ctx: PipelineContext) -> None:
        logger.info("=" * 60)
        logger.info("Step6: 视频生成")
        logger.info("=" * 60)

        clips_dir = ctx.output_dir / "clips"
        collections_dir = ctx.output_dir / "collections"
        clips_dir.mkdir(parents=True, exist_ok=True)
        collections_dir.mkdir(parents=True, exist_ok=True)

        vp = VideoProcessor(clips_dir=clips_dir, collections_dir=collections_dir)

        # 切割片段
        if ctx.clips_with_titles:
            ctx.generated_clips = vp.batch_extract_clips(
                ctx.video_path,
                [
                    {
                        "id": clip["id"],
                        "title": clip.get("generated_title", clip.get("outline", "")),
                        "start_time": clip["start_time"],
                        "end_time": clip["end_time"],
                    }
                    for clip in ctx.clips_with_titles
                ],
            )
            ctx.save_json("step6_clips_result", ctx.generated_clips)
            success = sum(1 for c in ctx.generated_clips if c.get("clip_path"))
            logger.info(f"切片生成: {success}/{len(ctx.generated_clips)} 成功")

        # 更新合集路径（指向已生成的 clips）
        for coll in ctx.collections:
            coll["clip_paths"] = [
                c["clip_path"]
                for c in ctx.generated_clips
                if c.get("id") in coll.get("clip_ids", []) and c.get("clip_path")
            ]

        # 拼接合集
        if ctx.collections:
            ctx.generated_collections = vp.create_collections_from_metadata(ctx.collections)
            ctx.save_json("step6_collections_result", ctx.generated_collections)
            success = sum(1 for c in ctx.generated_collections if c.get("collection_path"))
            logger.info(f"合集生成: {success}/{len(ctx.generated_collections)} 成功")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

_ALL_STEPS: List[type[PipelineStep]] = [
    Step1Outline,
    Step2Timeline,
    Step3Scoring,
    Step4Title,
    Step5Clustering,
    Step6Video,
]


class ClipPipeline:
    """
    6 步 AI 视频切片 Pipeline 编排器。

    支持：
      - 完整运行（6 步）
      - 从指定步骤恢复（用于失败后重跑）
      - 单步重跑（skip 指定步骤）

    Args:
        llm_client:     LLM 客户端（默认自动创建）
        output_dir:     输出目录
        min_score:      最低评分阈值
        chunk_minutes:  分块时长
        chunk_chars:    每块最大字符数
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        output_dir: str | Path = "output/clips",
        min_score: float = DEFAULT_MIN_SCORE,
        chunk_minutes: float = DEFAULT_CHUNK_MINUTES,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
    ):
        self.llm_client = llm_client or create_llm_client()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.min_score = min_score
        self.chunk_minutes = chunk_minutes
        self.chunk_chars = chunk_chars

        # 实例化各步骤
        self.steps: List[PipelineStep] = [
            cls() for cls in _ALL_STEPS
        ]

    def run(
        self,
        video_path: str | Path,
        srt_path: str | Path,
        skip_steps: List[str] | None = None,
        category: str = "knowledge",
    ) -> PipelineContext:
        """
        运行完整 Pipeline。

        Args:
            video_path:  视频文件路径
            srt_path:    字幕文件路径（.srt）
            skip_steps:  跳过的步骤名称列表（如 ["step5_clustering"]）
            category:    分类场景（knowledge/speech/entertainment）

        Returns:
            PipelineContext（含所有中间结果）
        """
        skip_steps = set(skip_steps or [])
        video_path = Path(video_path)
        srt_path = Path(srt_path)

        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if not srt_path.exists():
            raise FileNotFoundError(f"SRT 文件不存在: {srt_path}")

        ctx = PipelineContext(
            video_path=video_path,
            srt_path=srt_path,
            output_dir=self.output_dir,
            category=category,
            chunk_minutes=self.chunk_minutes,
            chunk_chars=self.chunk_chars,
            min_score=self.min_score,
            llm_client=self.llm_client,
        )

        for step in self.steps:
            if step.name in skip_steps:
                logger.info(f"跳过步骤: {step.name}")
                continue
            step.run(ctx)

        # 保存最终元数据
        ctx.save_json("clips_metadata", {
            "clips": ctx.generated_clips,
            "collections": ctx.generated_collections,
            "clips_with_titles": ctx.clips_with_titles,
            "high_score_clips": ctx.high_score_clips,
        })

        logger.info("=" * 60)
        logger.info("Pipeline 完成!")
        logger.info(f"输出目录: {ctx.output_dir}")
        logger.info(f"切片: {len(ctx.generated_clips)} 个")
        logger.info(f"合集: {len(ctx.generated_collections)} 个")
        logger.info("=" * 60)
        return ctx


def run_pipeline(
    video_path: str,
    srt_path: str,
    output_dir: str = "output/clips",
    llm_client: LLMClient | None = None,
    min_score: float = DEFAULT_MIN_SCORE,
    skip_steps: List[str] | None = None,
) -> PipelineContext:
    """快捷函数：运行完整 Pipeline"""
    pipeline = ClipPipeline(
        llm_client=llm_client,
        output_dir=output_dir,
        min_score=min_score,
    )
    return pipeline.run(video_path, srt_path, skip_steps=skip_steps)

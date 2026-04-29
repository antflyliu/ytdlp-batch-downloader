"""
monitor.detector — 新视频检测器
对比 API 返回结果与数据库已有记录，筛出真正的新视频
"""
import logging_config
import monitor.db as _db

_log = logging_config.get_logger("monitor.detector")


def detect_new(videos: list[dict]) -> list[dict]:
    """
    从 API 返回的视频列表中，筛出真正的新视频

    :param videos: API 返回的原始视频列表
    :return: 仅包含新增视频的列表（不在 monitor_videos 表中的）
    """
    if not videos:
        return []

    video_ids = [v["video_id"] for v in videos]
    existing_ids = _get_existing_ids(video_ids)
    all_ids = set(video_ids)
    new_ids = all_ids - existing_ids
    new_videos = [v for v in videos if v["video_id"] in new_ids]

    _log.info(f"检测完成: API返回={len(videos)} 已有={len(existing_ids)} 新增={len(new_videos)}")
    return new_videos


def _get_existing_ids(video_ids: list[str]) -> set[str]:
    """查询数据库，返回传入 video_ids 中已存在的 video_id"""
    if not video_ids:
        return set()
    placeholders = ",".join("?" * len(video_ids))
    with _db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT video_id FROM monitor_videos WHERE video_id IN ({placeholders})",
            video_ids,
        ).fetchall()
    return {r[0] for r in rows}

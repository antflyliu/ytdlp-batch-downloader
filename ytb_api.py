import os
import time
from datetime import datetime, timedelta
from typing import Literal
import pandas as pd
import logging_config
from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_exponential

"""
YouTube Data API 概览：https://developers.google.com/youtube/v3/getting-started?hl=zh-cn
"""


class YouTubeDataCollector:
    def __init__(
        self,
        api_key,
        view_threshold=1000000,
        proxy=None,
        save_path=None,
        logger_callback=None,
        max_limit=100,
        published_after_days=None,
        fetch_mode: Literal["search", "playlist"] = "search",
        uploads_playlist_id: str | None = None,
        uploads_playlist_channel_id: str | None = None,
    ):
        """
        初始化收集器
        :param api_key: YouTube API密钥
        :param view_threshold: 视频观看量阈值
        :param proxy: 代理设置
        :param save_path: 数据保存路径
        :param logger_callback: 日志回调函数
        :param max_limit: 最多收集多少条符合条件的视频后停止，默认100
        :param published_after_days: 限定获取最近N天内的视频，减少无效翻页，默认None（不限）
        :param fetch_mode: 视频获取模式，"search"（默认）用 search.list（最新优先），
                           "playlist" 用 playlistItems.list（上传顺序，最老在前）
        :param uploads_playlist_id: 预知的 uploads 播放列表ID（来自 get_channel_data，可省1次API调用）
        :param uploads_playlist_channel_id: 与 uploads_playlist_id 对应的频道 ID；同时传入时按频道键缓存，
            避免同一实例用于多频道时误复用。仅传 uploads_playlist_id 时：首次 _get_uploads_playlist_id
            会把该 ID 绑定到当时传入的 channel_id（兼容旧调用）。
        """
        # 配置代理
        if proxy:
            os.environ['HTTP_PROXY'] = proxy
            os.environ['HTTPS_PROXY'] = proxy

        self.api_key = api_key
        self.youtube = build('youtube', 'v3', developerKey=api_key)
        self.logger_callback = logger_callback
        self.view_threshold = view_threshold
        self.max_limit = max_limit
        self.published_after_days = published_after_days
        self.fetch_mode = fetch_mode
        # 按 channel_id 缓存 uploads 播放列表 ID（生产级：避免跨频道误用单字段缓存）
        self._uploads_playlist_by_channel: dict[str, str] = {}
        self._unbound_uploads_playlist_id: str | None = None
        if uploads_playlist_id and uploads_playlist_channel_id:
            self._uploads_playlist_by_channel[uploads_playlist_channel_id] = uploads_playlist_id
        elif uploads_playlist_id:
            self._unbound_uploads_playlist_id = uploads_playlist_id

        # 验证并设置保存路径
        if not save_path:
            raise ValueError("必须指定保存路径")
        self.video_save_path = save_path

        # 使用共享日志配置（所有模块写入同一日志文件）
        self.logger = logging_config.get_logger("ytb_api")

    def log_message(self, message):
        """统一的日志记录函数"""
        self.logger.info(message)
        if self.logger_callback:
            self.logger_callback(message)

    def _incr_quota(self, calls: int = 1) -> None:
        """每次 API 调用后自动 +1（用于 quota 追踪）"""
        try:
            # 延迟 import，避免循环依赖；失败时静默跳过
            import monitor.quota as _quota
            _quota.incr(self.api_key, calls=calls)
        except Exception:
            pass

    def extract_channel_info(self, input_str):
        """
        从多种输入格式中提取频道信息
        支持的格式：
        1. 频道ID (UC...)
        2. 频道URL (https://www.youtube.com/@...)
        3. 频道用户名 (@...)
        """
        try:
            self.log_message(f"正在处理输入: {input_str}")

            # 1. 检查是否是频道ID (UC开头)
            if input_str.startswith('UC'):
                self.log_message("检测到频道ID格式")
                return self.get_channel_by_id(input_str)

            # 2. 检查是否是频道URL或用户名
            if '/@' in input_str or input_str.startswith('@'):
                self.log_message("检测到频道用户名格式")
                username = input_str.split('/@')[-1].split('/')[0].strip() if '/@' in input_str else input_str.strip()
                return self.get_channel_by_username(username)

            self.log_message(f"无法识别的输入格式: {input_str}")
            return None
        except Exception as e:
            self.log_message(f"提取频道信息时出错: {str(e)}")
            return None

    def get_channel_by_id(self, channel_id):
        """直接通过频道ID获取信息"""
        try:
            request = self.youtube.channels().list(
                part="snippet,statistics,brandingSettings",
                id=channel_id
            )
            response = request.execute()
            self._incr_quota()

            if response.get('items'):
                channel = response['items'][0]
                self.log_message(f"成功获取频道信息: {channel['snippet']['title']}")
                return channel
            else:
                self.log_message(f"未找到频道ID: {channel_id}")
                return None

        except Exception as e:
            self.log_message(f"获取频道信息时出错: {str(e)}")
            return None

    def get_channel_by_username(self, username):
        """
        通过用户名/handle 获取频道信息（优先 channels().list，失败才用 search）
        channels().list(forHandle=) = 1 unit
        search().list(type=channel) = 100 units
        """
        clean_username = username.lstrip('@')
        self.log_message(f"正在获取频道信息，用户名: {clean_username}")

        # ★ 方案1: channels().list(forHandle=) — 仅需 1 unit
        try:
            request = self.youtube.channels().list(
                part="snippet,statistics,brandingSettings,contentDetails",
                forHandle=clean_username,
            )
            response = request.execute()
            self._incr_quota()
            if response.get('items'):
                channel = response['items'][0]
                self.log_message(f"直接获取频道成功 (channels.forHandle): {channel['snippet']['title']}")
                return channel
            self.log_message(f"channels.forHandle 未找到，尝试 search.list")
        except Exception as e:
            self.log_message(f"channels.forHandle 查询失败: {e}，尝试 search.list")

        # ★ 方案2: search().list — 需要 100 units（仅作为 fallback）
        try:
            request = self.youtube.search().list(
                part="snippet",
                q=clean_username,
                type="channel",
                maxResults=5,
            )
            response = request.execute()
            self._incr_quota(100)  # search().list = 100 units
            if response.get('items'):
                channel_id = response['items'][0]['id']['channelId']
                channel_request = self.youtube.channels().list(
                    part="snippet,statistics,brandingSettings",
                    id=channel_id,
                )
                channel_response = channel_request.execute()
                self._incr_quota()
                if channel_response.get('items'):
                    channel = channel_response['items'][0]
                    self.log_message(f"search.list 找到频道: {channel['snippet']['title']}")
                    return channel
            self.log_message(f"search.list 也未找到频道: {clean_username}")
        except Exception as e:
            self.log_message(f"search.list 查询失败: {e}")

        return None

    def get_channel_data(self, input_str):
        """获取频道数据的主方法（包含 uploads_playlist_id，避免重复请求）"""
        try:
            channel = self.extract_channel_info(input_str)
            if not channel:
                self.log_message(f"无法获取频道信息: {input_str}")
                return None

            # 从 channel 中提取 uploads_playlist_id（get_channel_by_username 已拉取 contentDetails）
            uploads_playlist_id = None
            try:
                uploads_playlist_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            except Exception:
                pass

            channel_data = {
                'channel_name': channel['snippet']['title'],
                'description': channel['snippet']['description'],
                'subscriber_count': channel['statistics'].get('subscriberCount', 'N/A'),
                'view_count': channel['statistics'].get('viewCount', 'N/A'),
                'video_count': channel['statistics'].get('videoCount', 'N/A'),
                'created_date': channel['snippet']['publishedAt'],
                'country': channel['snippet'].get('country', 'Not specified'),
                'channel_id': channel['id'],
                'uploads_playlist_id': uploads_playlist_id,
            }

            self.log_message(f"成功获取频道信息: {channel_data['channel_name']}")
            self.log_message(f"频道总视频数: {channel_data['video_count']}")
            return channel_data

        except Exception as e:
            self.log_message(f"获取频道数据时出错: {str(e)}")
            raise

    def get_videos_details(self, video_ids):
        """获取视频详细信息，按 API 上限每批最多 50 个 ID"""
        results = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            items = self._fetch_video_batch(batch)
            results.extend(items)
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def _fetch_video_batch(self, batch):
        """单批次请求视频详情（最多 50 个），失败时仅重试本批次"""
        try:
            request = self.youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=','.join(batch)
            )
            response = request.execute()
            self._incr_quota()
            self.log_message(f"成功获取一批 {len(batch)} 个视频的详情")
            return response['items']
        except Exception as e:
            self.log_message(f"获取视频详情时出错 (本批 {len(batch)} 个): {str(e)}")
            raise


    def _get_uploads_playlist_id(self, channel_id: str) -> str | None:
        """
        获取频道的上传视频播放列表ID（Uploads 播放列表）
        失败时指数退避重试（1s → 2s → 4s），最多 3 次。
        全部失败返回 None，不触发 search.list（避免高额 quota 消耗）。

        :param channel_id: 频道ID
        :return: uploads 播放列表ID，失败返回 None
        """
        cached = self._uploads_playlist_by_channel.get(channel_id)
        if cached is not None:
            self.log_message(f"复用缓存的 uploads_playlist_id ({channel_id}): {cached}")
            return cached

        if self._unbound_uploads_playlist_id is not None:
            pid = self._unbound_uploads_playlist_id
            self._unbound_uploads_playlist_id = None
            self._uploads_playlist_by_channel[channel_id] = pid
            self.log_message(
                f"将构造时传入的 uploads_playlist_id 绑定到频道 {channel_id}: {pid}"
            )
            return pid

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                request = self.youtube.channels().list(
                    part="contentDetails",
                    id=channel_id,
                )
                response = request.execute()
                self._incr_quota()
                if response.get("items"):
                    uploads_playlist_id = response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                    self._uploads_playlist_by_channel[channel_id] = uploads_playlist_id
                    self.log_message(f"获取频道 uploads 播放列表ID: {uploads_playlist_id}")
                    return uploads_playlist_id
                else:
                    self.log_message(f"未找到频道 contentDetails: {channel_id}")
                    if attempt < max_attempts:
                        backoff = 2 ** (attempt - 1)
                        self.log_message(f"第 {attempt} 次尝试失败，{backoff}s 后重试...")
                        time.sleep(backoff)
                        continue
                    return None
            except Exception as e:
                self.log_message(f"获取 uploads 播放列表ID时出错 (第 {attempt} 次): {str(e)}")
                if attempt < max_attempts:
                    backoff = 2 ** (attempt - 1)
                    self.log_message(f"{backoff}s 后重试...")
                    time.sleep(backoff)
                else:
                    self.log_message("重试次数耗尽，无法获取 uploads_播放列表")
                    return None
        return None

    def probe_uploads_playlist_id(self, channel_id: str) -> str | None:
        """
        单次 channels.list(part=contentDetails) 查询 Uploads 列表 ID（约 1 quota unit）。
        不写入实例内 _uploads_playlist_by_channel，专供频道元数据健康检查。
        """
        try:
            request = self.youtube.channels().list(
                part="contentDetails",
                id=channel_id,
            )
            response = request.execute()
            self._incr_quota()
            if not response.get("items"):
                self.log_message(f"probe: 无频道项 {channel_id}")
                return None
            return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        except Exception as e:
            self.log_message(f"probe_uploads_playlist_id 失败: {e}")
            return None

    def _get_channel_videos_by_playlist(self, channel_id: str):
        """
        通过 playlistItems.list 获取频道视频（使用 Uploads 播放列表）

        注意：playlistItems.list 按上传顺序返回（最老在前，最新在最后），
        适合需要按上传顺序处理或获取全部视频的场景。
        API 成本低（1 unit/请求 vs search.list 的 100 units）。

        :param channel_id: 频道ID
        :return: 符合条件的视频列表（按上传顺序，最老→最新）
        """
        try:
            uploads_playlist_id = self._get_uploads_playlist_id(channel_id)
        except Exception as e:
            self.log_message(f"获取 uploads_playlist_id 时异常: {e}，跳过本次视频获取")
            return []

        if not uploads_playlist_id:
            self.log_message(
                "无法获取 uploads 播放列表（已重试 3 次），跳过本次视频获取，"
                "不触发 search.list 以节省 quota"
            )
            return []

        videos = []
        next_page_token = None
        total_videos_found = 0
        total_videos_filtered = 0
        page_count = 0
        exhausted_reason = None

        # 构建 publishedAfter 时间过滤
        published_after = None
        if self.published_after_days:
            published_after = (
                datetime.utcnow() - timedelta(days=self.published_after_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.log_message(
                f"限定时间范围：最近 {self.published_after_days} 天（{published_after} 之后）"
            )

        self.log_message(
            f"目标：收集最多 {self.max_limit} 条符合条件的视频（观看数 >= {self.view_threshold}）"
        )
        self.log_message(f"使用 playlistItems.list 模式（Uploads 播放列表: {uploads_playlist_id}）")

        try:
            while True:
                try:
                    page_count += 1
                    self.log_message(
                        f"正在获取播放列表视频... (第 {page_count} 页)"
                    )

                    request_kwargs = {
                        "part": "snippet,contentDetails",
                        "playlistId": uploads_playlist_id,
                        "maxResults": 50,
                        "pageToken": next_page_token,
                    }
                    request = self.youtube.playlistItems().list(**request_kwargs)
                    response = request.execute()
                    self._incr_quota()

                    if not response.get("items"):
                        exhausted_reason = "播放列表中没有更多视频"
                        self.log_message(exhausted_reason)
                        break

                    # 提取 videoId
                    video_ids = []
                    for item in response["items"]:
                        rid = item.get("snippet", {}).get("resourceId", {})
                        if rid.get("kind") == "youtube#video":
                            video_ids.append(rid["videoId"])

                    total_videos_found += len(video_ids)
                    self.log_message(f"本页找到 {len(video_ids)} 个视频")

                    # 时间过滤：检查第一页最早视频是否在时间窗口内
                    if published_after and page_count == 1 and video_ids:
                        first_item = response["items"][0]
                        first_published = first_item.get("snippet", {}).get("publishedAt", "")
                        first_dt = datetime.strptime(first_published, "%Y-%m-%dT%H:%M:%SZ")
                        window_start = datetime.utcnow() - timedelta(days=self.published_after_days)
                        if first_dt < window_start:
                            exhausted_reason = (
                                f"播放列表中最老的视频 ({first_published}) "
                                f"早于时间窗口起点 ({window_start.strftime('%Y-%m-%dT%H:%M:%SZ')})"
                            )
                            self.log_message(exhausted_reason)
                            break

                    # 获取视频详情
                    try:
                        video_details = self.get_videos_details(video_ids)
                        self.log_message(
                            f"成功获取 {len(video_details)} 个视频的详细信息"
                        )

                        # 筛选观看数大于阈值的视频
                        filtered_videos = []
                        for video in video_details:
                            try:
                                view_count = int(
                                    video["statistics"].get("viewCount", 0)
                                )
                                self.log_message(
                                    f"视频 {video['id']} 观看数: {view_count}"
                                )
                                if view_count >= self.view_threshold:
                                    filtered_videos.append(video)
                                    self.log_message(
                                        f"  ✓ 符合条件（>= {self.view_threshold}）"
                                    )
                                else:
                                    self.log_message(
                                        f"  ✗ 不符合条件（< {self.view_threshold}）"
                                    )
                            except ValueError:
                                self.log_message(
                                    f"视频 {video['id']} 观看数无效"
                                )
                                continue

                        total_videos_filtered += len(filtered_videos)
                        self.log_message(
                            f"本页筛选出 {len(filtered_videos)} 个符合条件的视频"
                        )
                        videos.extend(filtered_videos)

                    except Exception as e:
                        self.log_message(f"获取视频详情时出错: {str(e)}")
                        if "quotaExceeded" in str(e):
                            raise
                        continue

                    # ★ 收集够 max_limit 条就停止
                    if len(videos) >= self.max_limit:
                        videos = videos[: self.max_limit]
                        exhausted_reason = f"已达到收集上限 {self.max_limit} 条"
                        self.log_message(exhausted_reason)
                        break

                    next_page_token = response.get("nextPageToken")
                    if not next_page_token:
                        exhausted_reason = "没有更多页面"
                        self.log_message(exhausted_reason)
                        break

                    self.log_message(
                        f"准备获取下一页数据 (当前累计 {len(videos)} 条)"
                    )

                except Exception as e:
                    self.log_message(f"获取播放列表视频时出错: {str(e)}")
                    if "quotaExceeded" in str(e):
                        raise
                    exhausted_reason = f"API错误: {str(e)}"
                    continue

            self.log_message(f"\n频道视频获取统计 (playlistItems.list 模式):")
            self.log_message(f"- 终止原因: {exhausted_reason}")
            self.log_message(f"- 总共翻页数: {page_count}")
            self.log_message(f"- API返回视频总数: {total_videos_found}")
            self.log_message(f"- 符合观看数阈值的视频数: {total_videos_filtered}")
            self.log_message(f"- 最终收集到的视频数: {len(videos)}")

            return videos

        except Exception as e:
            self.log_message(f"获取频道视频时出错: {str(e)}")
            raise

    def _get_channel_videos_by_search(self, channel_id: str):
        """
        通过 search.list 获取频道视频（使用 search.list，按最新优先）

        :param channel_id: 频道ID
        :return: 符合条件的视频列表（按最新优先排列）
        """
        videos = []
        next_page_token = None
        total_videos_found = 0
        total_videos_filtered = 0
        page_count = 0
        exhausted_reason = None

        published_after = None
        if self.published_after_days:
            published_after = (
                datetime.utcnow() - timedelta(days=self.published_after_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.log_message(
                f"限定时间范围：最近 {self.published_after_days} 天（{published_after} 之后）"
            )

        self.log_message(
            f"目标：收集最多 {self.max_limit} 条符合条件的视频（观看数 >= {self.view_threshold}）"
        )
        self.log_message(f"使用 search.list 模式（最新优先）")

        try:
            while True:
                try:
                    page_count += 1
                    self.log_message(
                        f"正在获取频道 {channel_id} 的视频列表... (第 {page_count} 页)"
                    )

                    request_kwargs = {
                        "part": "id",
                        "channelId": channel_id,
                        "maxResults": 50,
                        "pageToken": next_page_token,
                        "type": "video",
                        "order": "date",
                    }
                    if published_after:
                        request_kwargs["publishedAfter"] = published_after

                    request = self.youtube.search().list(**request_kwargs)
                    response = request.execute()
                    self._incr_quota(100)  # search().list = 100 units

                    if not response.get("items"):
                        exhausted_reason = "没有找到更多视频"
                        self.log_message(exhausted_reason)
                        break

                    video_ids = [
                        item["id"]["videoId"] for item in response["items"]
                    ]
                    total_videos_found += len(video_ids)
                    self.log_message(f"本页找到 {len(video_ids)} 个视频")

                    try:
                        video_details = self.get_videos_details(video_ids)
                        self.log_message(
                            f"成功获取 {len(video_details)} 个视频的详细信息"
                        )

                        filtered_videos = []
                        for video in video_details:
                            try:
                                view_count = int(
                                    video["statistics"].get("viewCount", 0)
                                )
                                self.log_message(
                                    f"视频 {video['id']} 观看数: {view_count}"
                                )
                                if view_count >= self.view_threshold:
                                    filtered_videos.append(video)
                                    self.log_message(
                                        f"  ✓ 符合条件（>= {self.view_threshold}）"
                                    )
                                else:
                                    self.log_message(
                                        f"  ✗ 不符合条件（< {self.view_threshold}）"
                                    )
                            except ValueError:
                                self.log_message(
                                    f"视频 {video['id']} 观看数无效"
                                )
                                continue

                        total_videos_filtered += len(filtered_videos)
                        self.log_message(
                            f"本页筛选出 {len(filtered_videos)} 个符合条件的视频"
                        )
                        videos.extend(filtered_videos)

                    except Exception as e:
                        self.log_message(f"获取视频详情时出错: {str(e)}")
                        if "quotaExceeded" in str(e):
                            raise
                        continue

                    if len(videos) >= self.max_limit:
                        videos = videos[: self.max_limit]
                        exhausted_reason = (
                            f"已达到收集上限 {self.max_limit} 条"
                        )
                        self.log_message(exhausted_reason)
                        break

                    next_page_token = response.get("nextPageToken")
                    if not next_page_token:
                        exhausted_reason = "没有更多页面"
                        self.log_message(exhausted_reason)
                        break

                    self.log_message(
                        f"准备获取下一页数据 (当前累计 {len(videos)} 条)"
                    )

                except Exception as e:
                    self.log_message(f"获取频道视频列表时出错: {str(e)}")
                    if "quotaExceeded" in str(e):
                        raise
                    exhausted_reason = f"API错误: {str(e)}"
                    continue

            self.log_message(f"\n频道视频获取统计 (search.list 模式):")
            self.log_message(f"- 终止原因: {exhausted_reason}")
            self.log_message(f"- 总共翻页数: {page_count}")
            self.log_message(f"- API返回视频总数: {total_videos_found}")
            self.log_message(f"- 符合观看数阈值的视频数: {total_videos_filtered}")
            self.log_message(f"- 最终收集到的视频数: {len(videos)}")

            return videos

        except Exception as e:
            self.log_message(f"获取频道视频时出错: {str(e)}")
            raise

    def get_channel_videos(self, channel_id):
        """
        获取频道的最新 N 条符合条件的视频（自动根据 fetch_mode 选择获取方式）

        :param channel_id: 频道ID
        :return: 符合条件的视频列表
        """
        if self.fetch_mode == "playlist":
            self.log_message(f"使用 playlistItems.list 模式获取频道视频: {channel_id}")
            return self._get_channel_videos_by_playlist(channel_id)
        else:
            self.log_message(f"使用 search.list 模式获取频道视频: {channel_id}")
            return self._get_channel_videos_by_search(channel_id)

    def save_videos_to_excel(self, channel_id, videos, original_url):
        """将视频数据保存到Excel"""
        try:
            video_data = []
            processed_video_ids = set()

            # 从URL中提取用户名
            username = None
            if '/@' in original_url:
                username = original_url.split('/@')[1].split('/')[0].strip()

            for video in videos:
                video_id = video['id']
                if video_id in processed_video_ids:
                    self.log_message(f"跳过重复视频ID: {video_id}")
                    continue

                processed_video_ids.add(video_id)
                video_data.append({
                    'title': video['snippet']['title'],
                    'description': video['snippet']['description'],
                    'published_at': video['snippet']['publishedAt'],
                    'view_count': video['statistics'].get('viewCount', 'N/A'),
                    'like_count': video['statistics'].get('likeCount', 'N/A'),
                    'comment_count': video['statistics'].get('commentCount', 'N/A'),
                    'tags': ','.join(video['snippet'].get('tags', [])),
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'video_id': video_id
                })

            if video_data:
                # 转换为DataFrame
                df = pd.DataFrame(video_data)

                # 记录原始数据
                original_count = len(df)
                self.log_message(f"原始数据数量: {original_count}")

                # 只基于video_id去重
                df = df.drop_duplicates(subset=['video_id'], keep='first')

                # 记录清洗后的数据
                cleaned_count = len(df)
                self.log_message(f"清洗后数据数量: {cleaned_count}")

                if original_count > cleaned_count:
                    self.log_message(f"清除了 {original_count - cleaned_count} 条重复数据")
                    duplicate_ids = df['video_id'].value_counts()[df['video_id'].value_counts() > 1].index
                    if len(duplicate_ids) > 0:
                        self.log_message(f"重复的视频ID: {list(duplicate_ids)}")

                # 删除video_id列
                df = df.drop('video_id', axis=1)

                # 使用用户名作为文件名，如果无法获取用户名则使用频道ID
                if username:
                    filename = f"{username}_videos.xlsx"
                else:
                    filename = f"{channel_id}_videos.xlsx"

                output_path = os.path.join(self.video_save_path, filename)
                df.to_excel(output_path, index=False)
                self.log_message(f"视频数据已保存到: {output_path}")

            else:
                self.log_message("没有数据需要保存")

        except Exception as e:
            self.log_message(f"保存视频数据时出错: {str(e)}")
            raise

    def process_excel_file(self, excel_path):
        """处理Excel文件"""
        try:
            # 读取Excel文件，确保不跳过任何行
            try:
                df = pd.read_excel(excel_path, dtype=str)
                df = df.dropna(how='all')
                df = df.reset_index(drop=True)

                self.log_message(f"成功读取Excel文件，共有 {len(df)} 个频道待处理")
                self.log_message(f"读取到的URL列表：{df.iloc[:, 0].tolist()}")
            except Exception as e:
                self.log_message(f"读取Excel文件失败: {str(e)}")
                return

            if df.empty:
                self.log_message("Excel文件为空")
                return

            # 确保所需的列存在
            required_columns = ['channel_name', 'description', 'subscriber_count',
                                'view_count', 'video_count', 'created_date', 'country']  # 添加 video_count
            for col in required_columns:
                if col not in df.columns:
                    df[col] = ''

            channel_urls = df.iloc[:, 0].astype(str).tolist()
            success_count = 0

            for idx, url in enumerate(channel_urls):
                if pd.isna(url) or url.strip() == '':
                    self.log_message(f"第 {idx + 1} 行的URL为空，已跳过")
                    continue

                try:
                    self.log_message(f"正在处理第 {idx + 1}/{len(channel_urls)} 个频道: {url}")

                    # 使用新的get_channel_data方法
                    channel_data = self.get_channel_data(url)
                    if channel_data:
                        for col, value in channel_data.items():
                            if col != 'channel_id':
                                df.loc[idx, col] = value

                        self.log_message(f"开始获取频道 {url} 的视频数据...")
                        videos = self.get_channel_videos(channel_data['channel_id'])
                        if videos:
                            self.save_videos_to_excel(channel_data['channel_id'], videos, url)
                            self.log_message(f"成功保存频道 {url} 的视频数据，共 {len(videos)} 个视频")
                            # 添加统计信息
                            self.log_message(f"频道统计信息:")
                            self.log_message(f"- 总视频数: {channel_data['video_count']}")
                            self.log_message(f"- 符合观看量阈值的视频数: {len(videos)}")
                        else:
                            self.log_message(f"频道 {url} 没有符合条件的视频（观看数 >= {self.view_threshold}）")

                        success_count += 1
                    else:
                        self.log_message(f"无法获取频道数据: {url}")

                except Exception as e:
                    self.log_message(f"处理频道 {url} 时出错: {str(e)}")
                    continue

            self.log_message(f"总共处理了 {len(channel_urls)} 个频道，成功 {success_count} 个")

            # 保存更新后的Excel文件
            try:
                base_path = os.path.splitext(excel_path)[0]
                current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_excel_path = f"{base_path}_updated_{current_time}.xlsx"

                df.to_excel(new_excel_path, index=False)
                self.log_message(f"数据已保存到新文件: {new_excel_path}")

            except Exception as e:
                self.log_message(f"保存Excel文件时出错: {str(e)}")
                desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
                backup_file = os.path.join(desktop_path, f"youtube_data_backup_{current_time}.xlsx")
                try:
                    df.to_excel(backup_file, index=False)
                    self.log_message(f"数据已保存到备份文件: {backup_file}")
                except Exception as e2:
                    self.log_message(f"保存备份文件也失败: {str(e2)}")
                    raise

        except Exception as e:
            self.log_message(f"处理Excel文件时出错: {str(e)}")
            raise

    def run(self, excel_path):
        """运行主程序"""
        try:
            self.log_message(
                f"开始处理数据... (max_limit={self.max_limit}, "
                f"view_threshold={self.view_threshold}, "
                f"published_after_days={self.published_after_days}, "
                f"fetch_mode={self.fetch_mode})"
            )
            self.process_excel_file(excel_path)
            self.log_message("数据处理完成！")
        except Exception as e:
            self.log_message(f"程序运行出错: {str(e)}")
            raise

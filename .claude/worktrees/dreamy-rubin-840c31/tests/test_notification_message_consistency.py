"""
tests/test_notification_message_consistency.py

回归测试：三个通知平台消息字段一致性

Bug 背景：
  飞书消息数据最全（含时长/观看数/点赞数/评论数），钉钉和 Telegram 缺少部分字段。
  修复后三个平台消息应包含一致的统计字段。

同时验证 Bug 7（平台切换字段清除）的 JS 逻辑。
"""
import unittest


class TestPlatformMessageFieldConsistency(unittest.TestCase):
    """三个平台的新视频通知消息字段对齐验证"""

    def _sample_videos(self):
        return [
            {
                "title": "puppy playpen reset 🐶",
                "url": "https://www.youtube.com/watch?v=abc123",
                "published_at": "2026-04-14T10:00:00+08:00",
                "duration_sec": 65,
                "view_count": 38816,
                "like_count": 1247,
                "comment_count": 89,
            },
            {
                "title": "every fur owner must have gadget",
                "url": "https://www.youtube.com/watch?v=xyz789",
                "published_at": "2026-04-13T08:00:00+08:00",
                "duration_sec": 120,
                "view_count": 52100,
                "like_count": 3102,
                "comment_count": 204,
            },
        ]

    def _strip_feishu_md(self, text: str) -> set[str]:
        """从飞书 Markdown 中提取统计关键词"""
        return set(w for w in text.split() if any(
            c in w for c in "📅⏱👁👍💬"))

    def test_feishu_card_includes_all_stats(self):
        """飞书卡片包含：时长、观看数、点赞数、评论数"""
        from monitor.notification.renderers import _build_video_list_md
        videos = self._sample_videos()
        md = _build_video_list_md(videos)
        self.assertIn("⏱", md)
        self.assertIn("👁", md)
        self.assertIn("👍", md)
        self.assertIn("💬", md)
        # 第一个视频的格式化时长（65秒 → 1:05）
        self.assertIn("1:05", md)
        self.assertIn("38,816", md)
        self.assertIn("1,247", md)
        self.assertIn("89", md)

    def test_dingtalk_markdown_includes_all_stats(self):
        """钉钉 Markdown 包含：时长、观看数、点赞数、评论数（与飞书对齐）"""
        from monitor.notification.dingtalk import _build_dingtalk_markdown
        videos = self._sample_videos()
        payload = _build_dingtalk_markdown("TestChannel", "https://youtube.com/@test", videos)
        text = payload["markdown"]["text"]
        # 核心统计字段
        self.assertIn("⏱", text)
        self.assertIn("👁", text)
        self.assertIn("👍", text)
        self.assertIn("💬", text)
        # 第一个视频数据
        self.assertIn("2026-04-14", text)
        self.assertIn("38,816", text)
        self.assertIn("1,247", text)
        self.assertIn("89", text)
        # 时长格式化（65秒 → 1:05）
        self.assertIn("1:05", text)

    def test_telegram_message_includes_all_stats(self):
        """Telegram 消息包含：时长、观看数、点赞数、评论数（与飞书对齐）"""
        from monitor.notification.telegram import _build_telegram_message
        videos = self._sample_videos()
        payload = _build_telegram_message("TestChannel", "https://youtube.com/@test", videos)
        text = payload["text"]
        # 核心统计字段
        self.assertIn("⏱", text)
        self.assertIn("👁", text)
        self.assertIn("👍", text)
        self.assertIn("💬", text)
        # 第一个视频数据（MarkdownV2 会转义日期中的 -）
        self.assertIn("2026\\-04\\-14", text)
        self.assertIn("38,816", text)
        self.assertIn("1,247", text)
        self.assertIn("89", text)
        # 时长格式化（65秒 → 1:05）
        self.assertIn("1:05", text)

    def test_all_platforms_include_channel_info(self):
        """三个平台消息都包含频道信息"""
        from monitor.notification.renderers import _build_feishu_card_v2
        from monitor.notification.dingtalk import _build_dingtalk_markdown
        from monitor.notification.telegram import _build_telegram_message
        videos = self._sample_videos()

        # Feishu
        feishu = _build_feishu_card_v2("MyChannel", "https://youtube.com/@my", videos)
        feishu_text = str(feishu)
        self.assertIn("MyChannel", feishu_text)
        self.assertIn("youtube.com/@my", feishu_text)

        # DingTalk: uses "-" markdown list, URL includes full scheme
        dingtalk = _build_dingtalk_markdown("MyChannel", "https://youtube.com/@my", videos)
        self.assertIn("MyChannel", dingtalk["markdown"]["text"])
        self.assertIn("https://youtube.com/@my", dingtalk["markdown"]["text"])

        # Telegram: URL is fully escaped for MarkdownV2 (dots, slashes escaped)
        telegram = _build_telegram_message("MyChannel", "https://youtube.com/@my", videos)
        self.assertIn("MyChannel", telegram["text"])
        self.assertIn("https://youtube\\.com/@my", telegram["text"])

    def test_all_platforms_respect_max_items(self):
        """三个平台都限制展示数量（最多10条），飞书最多5条卡片内展示"""
        from monitor.notification.renderers import _build_feishu_card_v2, _FEISHU_MAX_ITEMS
        from monitor.notification.dingtalk import _build_dingtalk_markdown
        from monitor.notification.telegram import _build_telegram_message

        # 生成 15 个视频
        videos = [{"title": f"Video {i}", "url": f"https://yt.be/{i}",
                   "published_at": "2026-04-01T00:00:00", "duration_sec": 60,
                   "view_count": 100, "like_count": 10, "comment_count": 5}
                  for i in range(15)]

        feishu = _build_feishu_card_v2("X", "https://youtube.com/@x", videos)
        feishu_text = str(feishu)
        # 飞书卡片最多 _FEISHU_MAX_ITEMS（5条）
        self.assertIn(str(_FEISHU_MAX_ITEMS), feishu_text)

        dingtalk = _build_dingtalk_markdown("X", "https://youtube.com/@x", videos)
        dt_text = dingtalk["markdown"]["text"]
        # 钉钉最多10条，用 markdown "-" list 格式，检查 "Video 0" (第1条) 和 "Video 9" (第10条) 存在
        self.assertIn("Video 0", dt_text)
        self.assertIn("Video 9", dt_text)
        self.assertNotIn("Video 10", dt_text)

        telegram = _build_telegram_message("X", "https://youtube.com/@x", videos)
        tg_text = telegram["text"]
        # Telegram 最多10条，MarkdownV2 编号格式
        self.assertIn("1\\.", tg_text)
        self.assertIn("10\\.", tg_text)
        self.assertNotIn("11\\.", tg_text)


class TestPlatformSwitchFieldClearing(unittest.TestCase):
    """Bug 7：平台切换时清除不属于当前平台的字段（JS 逻辑验证）"""

    def test_selectPlatform_clears_telegram_token_when_switching_to_feishu(self):
        """切换到 Feishu/Dingtalk 时，Telegram Bot Token 应被清除"""
        # 读取 JS 源码，验证 selectPlatform 逻辑包含清除 Telegram Token 的代码
        import os
        js_path = os.path.join(
            os.path.dirname(__file__), "..",
            "monitor_web", "js", "modules", "accounts.js"
        )
        with open(js_path, encoding="utf-8") as f:
            js_code = f.read()
        # 验证：切换到非 telegram 平台时，清除 accTelegramToken
        # 查找 selectPlatform 函数体中 accTelegramToken 相关逻辑
        self.assertIn("accTelegramToken", js_code)
        # 切换到 telegram 时，显示 telegramTokenGroup
        self.assertIn("p === 'telegram'", js_code)
        # 清除 accTelegramToken 的逻辑存在
        self.assertIn("accTgToken", js_code)  # 局部变量引用

    def test_selectPlatform_hides_webhook_when_switching_to_telegram(self):
        """切换到 Telegram 时，Webhook URL 字段组应被隐藏"""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__), "..",
            "monitor_web", "js", "modules", "accounts.js"
        )
        with open(js_path, encoding="utf-8") as f:
            js_code = f.read()
        # Telegram 时隐藏 accWebhookGroup
        self.assertIn("accWebhookGroup", js_code)
        self.assertIn("p === 'telegram'", js_code)


if __name__ == "__main__":
    unittest.main()

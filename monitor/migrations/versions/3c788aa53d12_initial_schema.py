"""initial_schema

Revision ID: 3c788aa53d12
Revises:
Create Date: 2026-04-06

对于全新数据库: alembic upgrade head — 创建全部表与索引
对于已有 SQLite: alembic stamp head — 标记为已应用（表结构已存在）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "3c788aa53d12"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── api_keys ─────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key_value", sa.String(256), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("daily_quota", sa.Integer, nullable=False, server_default=sa.text("10000")),
        sa.Column("quota_used", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("quota_reset_at", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
    )
    op.create_index("idx_api_keys_active", "api_keys", ["is_active"])

    # ── monitor_accounts ─────────────────────────────────────────────
    op.create_table(
        "monitor_accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("channel_url", sa.String(512), nullable=False),
        sa.Column(
            "api_key_id", sa.Integer,
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("api_key_env", sa.String(256), nullable=False),
        sa.Column("fetch_mode", sa.String(32), nullable=False, server_default="playlist"),
        sa.Column("fetch_limit", sa.Integer, nullable=False, server_default=sa.text("5")),
        sa.Column("scan_interval", sa.Integer, nullable=False, server_default=sa.text("5")),
        sa.Column("enabled", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("notify_enabled", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("notify_platform", sa.String(32), nullable=False, server_default="feishu"),
        sa.Column("webhook_url", sa.Text, nullable=True),
        sa.Column("feishu_message_mode", sa.String(32), nullable=False, server_default="card_json"),
        sa.Column("feishu_template_id", sa.String(128), nullable=True),
        sa.Column("feishu_scan_template_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
    )
    op.create_index("idx_accounts_channel_url", "monitor_accounts", ["channel_url"], unique=True)

    # ── monitor_events ───────────────────────────────────────────────
    op.create_table(
        "monitor_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "account_id", sa.Integer,
            sa.ForeignKey("monitor_accounts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("account_name", sa.String(256), nullable=False),
        sa.Column("scan_started_at", sa.String(64), nullable=False),
        sa.Column("scan_ended_at", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("total_videos", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("new_videos", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
    )
    op.create_index("idx_events_account_id", "monitor_events", ["account_id"])
    op.create_index("idx_events_started", "monitor_events", [sa.text("scan_started_at DESC")])

    # ── monitor_videos ───────────────────────────────────────────────
    op.create_table(
        "monitor_videos",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "account_id", sa.Integer,
            sa.ForeignKey("monitor_accounts.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "event_id", sa.Integer,
            sa.ForeignKey("monitor_events.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("channel_id", sa.String(64), nullable=True),
        sa.Column("channel_handle", sa.String(256), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("published_at", sa.String(64), nullable=False),
        sa.Column("upload_date", sa.String(16), nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("view_count", sa.Integer, nullable=True),
        sa.Column("like_count", sa.Integer, nullable=True),
        sa.Column("comment_count", sa.Integer, nullable=True),
        sa.Column("thumbnail_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.String(64), nullable=False),
        sa.Column("notify_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("notify_sent_at", sa.String(64), nullable=True),
        sa.Column("notify_error", sa.Text, nullable=True),
        sa.Column("download_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("download_at", sa.String(64), nullable=True),
        sa.Column("download_path", sa.Text, nullable=True),
        sa.Column("download_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
    )
    op.create_index("idx_monitor_videos_account_id", "monitor_videos", ["account_id"])
    op.create_index("idx_monitor_videos_event_id", "monitor_videos", ["event_id"])
    op.create_index("idx_monitor_videos_published", "monitor_videos", [sa.text("published_at DESC")])
    op.create_index("idx_monitor_videos_notify", "monitor_videos", ["notify_status"])

    # ── app_state ────────────────────────────────────────────────────
    op.create_table(
        "app_state",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )

    # ── monitor_notify_logs ──────────────────────────────────────────
    op.create_table(
        "monitor_notify_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "event_id", sa.Integer,
            sa.ForeignKey("monitor_events.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("account_id", sa.Integer, nullable=False),
        sa.Column("account_name", sa.String(256), nullable=False),
        sa.Column("video_count", sa.Integer, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("webhook_url", sa.Text, nullable=False),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("response_text", sa.Text, nullable=True),
        sa.Column("sent_at", sa.String(64), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("idx_notify_logs_event_id", "monitor_notify_logs", ["event_id"])
    op.create_index("idx_notify_logs_sent_at", "monitor_notify_logs", [sa.text("sent_at DESC")])

    # ── channel_meta_cache ───────────────────────────────────────────
    op.create_table(
        "channel_meta_cache",
        sa.Column("handle", sa.String(256), primary_key=True),
        sa.Column("channel_id", sa.String(64), nullable=False),
        sa.Column("channel_name", sa.String(256), nullable=True),
        sa.Column("uploads_playlist_id", sa.String(64), nullable=True),
        sa.Column("subscriber_count", sa.String(32), nullable=True),
        sa.Column("video_count", sa.String(32), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("cached_at", sa.String(64), nullable=False),
    )
    op.create_index("idx_channel_cache_channel_id", "channel_meta_cache", ["channel_id"])

    # ── api_quota_usage ──────────────────────────────────────────────
    op.create_table(
        "api_quota_usage",
        sa.Column("api_key_value", sa.String(256), nullable=False, primary_key=True),
        sa.Column("date_key", sa.String(16), nullable=False, primary_key=True),
        sa.Column("api_calls", sa.Integer, server_default=sa.text("0")),
        sa.Column("scans_done", sa.Integer, server_default=sa.text("0")),
        sa.Column("blocked_scans", sa.Integer, server_default=sa.text("0")),
        sa.Column("updated_at", sa.String(64), nullable=False),
    )
    op.create_index("idx_quota_date", "api_quota_usage", ["date_key"])

    # ── schema_migrations ────────────────────────────────────────────
    op.create_table(
        "schema_migrations",
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("applied_at", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("schema_migrations")
    op.drop_table("api_quota_usage")
    op.drop_table("channel_meta_cache")
    op.drop_table("monitor_notify_logs")
    op.drop_table("app_state")
    op.drop_table("monitor_videos")
    op.drop_table("monitor_events")
    op.drop_table("monitor_accounts")
    op.drop_table("api_keys")

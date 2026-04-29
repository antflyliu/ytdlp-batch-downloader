from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCOUNTS_API = ROOT / "frontend-vue" / "src" / "api" / "accounts.ts"
ACCOUNTS_VIEW = ROOT / "frontend-vue" / "src" / "views" / "Accounts.vue"


def test_account_update_route_injects_path_id(monkeypatch):
    import server.__main__ as server_main

    calls = []
    handler = object.__new__(server_main.MonitorHandler)
    monkeypatch.setattr(
        server_main.MonitorHandler,
        "_api_account_add",
        lambda self, body: calls.append(body),
    )

    handler._api_account_update("6", {"name": "The Hayeks"})

    assert calls == [{"name": "The Hayeks", "id": 6}]


def test_account_update_route_rejects_invalid_id():
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))

    handler._api_account_update("not-an-id", {"name": "The Hayeks"})

    assert sent == [({"error": "账户 ID 无效"}, 400)]


def test_account_video_status_filter_uses_top_level_db_query(monkeypatch):
    import server.__main__ as server_main

    calls = []
    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler.path = "/api/accounts/6/videos?status=failed"
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "get_account_videos_filtered",
        lambda account_id, status: calls.append((account_id, status)) or [{"id": 9}],
    )

    handler._api_account_videos("6")

    assert calls == [(6, "failed")]
    assert sent == [({
        "videos": [{"id": 9}],
        "total": 1,
        "page": 1,
        "page_size": 1,
        "pages": 1,
    }, 200)]


def test_account_update_omitted_optional_secrets_are_not_modified(monkeypatch):
    import server.__main__ as server_main

    calls = []
    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "update_account",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(server_main._scheduler, "is_running", lambda: False)

    server_main.MonitorHandler._api_account_add(
        handler,
        {
            "id": 6,
            "name": "The Hayeks",
            "channel_url": "@The_Hayeks",
            "api_key_id": 17,
            "fetch_mode": "playlist",
            "fetch_limit": 10,
            "scan_interval": 2,
            "enabled": True,
            "notify_enabled": True,
            "notify_platform": "telegram",
            "proxy_enabled": True,
            "proxy_pool_id": 3,
            "download_proxy_mode": "auto",
            "api_key_env": "YOUTUBE_Data_API_V3",
        },
    )

    assert sent == [({"ok": True, "id": 6}, 200)]
    update = calls[0]
    assert update["telegram_bot_token"] is server_main._db._UNSET
    assert update["dingtalk_sign_secret"] is server_main._db._UNSET
    assert update["webhook_url"] is server_main._db._UNSET
    assert update["feishu_template_id"] is server_main._db._UNSET
    assert update["feishu_scan_template_id"] is server_main._db._UNSET


def test_accounts_api_update_uses_canonical_post_endpoint():
    text = ACCOUNTS_API.read_text(encoding="utf-8")

    assert "`/api/accounts/${id}/update`" not in text
    assert "url: '/api/accounts', method: 'post', data: { ...data, id }" in text


def test_accounts_payload_omits_unedited_or_inactive_secret_fields():
    text = ACCOUNTS_VIEW.read_text(encoding="utf-8")

    assert "data.telegram_bot_token = MASKED_SECRET_VALUE" not in text
    assert "data.dingtalk_sign_secret = MASKED_SECRET_VALUE" not in text
    assert "delete data.telegram_bot_token" in text
    assert "delete data.dingtalk_sign_secret" in text
    assert "if (token) data.telegram_bot_token = token" in text
    assert "if (signSecret) data.dingtalk_sign_secret = signSecret" in text


def test_accounts_detail_action_opens_video_detail_modal():
    text = ACCOUNTS_VIEW.read_text(encoding="utf-8")

    assert "openDetailModal(row)" in text
    assert 't(\'videoDetail.title\')' in text
    assert ":columns=\"detailColumns\"" in text
    assert "loadAccountVideos" in text
    assert "batchDownloadSelected" in text
    assert "retryFailedVideos" in text


def test_accounts_api_exposes_video_detail_endpoints():
    text = ACCOUNTS_API.read_text(encoding="utf-8")

    assert "videos(accountId: number, params: object)" in text
    assert "`/api/accounts/${accountId}/videos`" in text
    assert "batchDownloadVideos(accountId: number, data: object)" in text
    assert "`/api/accounts/${accountId}/videos/batch-download`" in text
    assert "retryVideos(accountId: number, videoIds: number[])" in text
    assert "'/api/videos/retry'" in text
    assert "downloadTask(taskId: string)" in text

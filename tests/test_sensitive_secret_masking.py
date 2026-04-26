def test_config_endpoint_masks_sensitive_notification_tokens(monkeypatch):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "load_config",
        lambda: {
            "global_telegram_token": "123456789:secret-token",
            "global_dingtalk_sign_secret": "SECsecret",
            "llm_api_key": "sk-secret",
            "global_telegram_chat_id": "-100123",
        },
    )

    server_main.MonitorHandler._api_config(handler)

    assert sent == [
        (
            {
                "global_telegram_token": "***",
                "global_dingtalk_sign_secret": "***",
                "llm_api_key": "***",
                "global_telegram_chat_id": "-100123",
            },
            200,
        )
    ]


def test_masked_config_values_preserve_existing_secrets():
    import server.__main__ as server_main

    old_cfg = {
        "global_telegram_token": "123456789:old-token",
        "global_dingtalk_sign_secret": "SECold",
        "llm_api_key": "sk-old",
    }
    new_cfg = {
        "global_telegram_token": "***",
        "global_dingtalk_sign_secret": "",
        "llm_api_key": "sk-new",
    }

    merged = server_main._preserve_masked_config_values(new_cfg, old_cfg)

    assert merged["global_telegram_token"] == "123456789:old-token"
    assert merged["global_dingtalk_sign_secret"] == ""
    assert merged["llm_api_key"] == "sk-new"


def test_accounts_endpoint_masks_account_telegram_token(monkeypatch):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "list_accounts",
        lambda: [
            {
                "id": 7,
                "name": "Telegram account",
                "channel_url": "@example",
                "api_key_env": "YOUTUBE_Data_API_V3",
                "api_key_id": None,
                "fetch_mode": "playlist",
                "fetch_limit": 5,
                "scan_interval": 5,
                "enabled": 1,
                "notify_enabled": 1,
                "notify_platform": "telegram",
                "webhook_url": "",
                "telegram_bot_token": "123456789:secret-token",
                "dingtalk_sign_secret": "SECsecret",
                "feishu_message_mode": "card_json",
                "feishu_template_id": "",
                "feishu_scan_template_id": "",
                "proxy_pool_id": None,
                "proxy_enabled": 0,
                "download_proxy_mode": "auto",
            }
        ],
    )

    server_main.MonitorHandler._api_accounts(handler)

    assert sent[0][0][0]["telegram_bot_token"] == "***"
    assert sent[0][0][0]["dingtalk_sign_secret"] == "***"


def test_masked_account_token_preserves_existing_value(monkeypatch):
    import server.__main__ as server_main

    monkeypatch.setattr(
        server_main._db,
        "get_account",
        lambda account_id: {"telegram_bot_token": "123456789:old-token"},
    )

    assert (
        server_main._resolve_masked_account_secret(7, "telegram_bot_token", "***")
        == "123456789:old-token"
    )
    assert server_main._resolve_masked_account_secret(7, "telegram_bot_token", "") is None
    assert (
        server_main._resolve_masked_account_secret(7, "telegram_bot_token", "123456789:new-token")
        == "123456789:new-token"
    )


def test_masked_account_dingtalk_secret_preserves_existing_value(monkeypatch):
    import server.__main__ as server_main

    monkeypatch.setattr(
        server_main._db,
        "get_account",
        lambda account_id: {"dingtalk_sign_secret": "SECold"},
    )

    assert (
        server_main._resolve_masked_account_secret(7, "dingtalk_sign_secret", "***")
        == "SECold"
    )
    assert server_main._resolve_masked_account_secret(7, "dingtalk_sign_secret", "") is None
    assert (
        server_main._resolve_masked_account_secret(7, "dingtalk_sign_secret", "SECnew")
        == "SECnew"
    )


def test_dynamic_provider_config_masks_local_proxy_url(monkeypatch):
    import server.__main__ as server_main

    sent = []
    handler = object.__new__(server_main.MonitorHandler)
    handler._send_json = lambda data, status=200: sent.append((data, status))
    monkeypatch.setattr(
        server_main._db,
        "list_dynamic_proxy_providers",
        lambda: [
            {
                "id": 9,
                "name": "Local gateway",
                "enabled": 1,
                "billing_tier": "paid",
                "adapter_type": "local_gateway",
                "priority": 100,
                "refresh_interval_minutes": 0,
                "supports_cookies": 0,
                "supports_auto_download": 1,
                "supports_country_filter": 0,
                "supports_sticky_session": 0,
                "risk_level": "medium",
                "notes": "",
                "config_json": {
                    "local_proxy_url": "http://user:pass@example.com:8080",
                    "password": "secret",
                },
                "last_health_status": "",
                "last_health_checked_at": "",
                "last_error_message": "",
                "created_at": "",
                "updated_at": "",
            }
        ],
    )

    server_main.MonitorHandler._api_dynamic_providers_list(handler)

    provider = sent[0][0][0]
    assert provider["config_json"]["local_proxy_url"] == "***"
    assert provider["config_json"]["password"] == "***"


def test_masked_dynamic_provider_proxy_url_preserves_existing_value():
    from config.encryption import _merge_masked_config_secrets

    old_cfg = {"local_proxy_url": "http://user:pass@example.com:8080"}
    merged = _merge_masked_config_secrets({"local_proxy_url": "***"}, old_cfg)

    assert merged["local_proxy_url"] == "http://user:pass@example.com:8080"

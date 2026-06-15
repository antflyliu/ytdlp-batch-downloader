"""sph_cookie 字段应自动加密（与 llm_api_key 同套 Fernet 机制）。"""
import json
from pathlib import Path

import config.settings as settings


def test_sph_cookie_is_in_secret_config_keys():
    """sph_cookie 必须出现在 _SECRET_CONFIG_KEYS 中，确保 load/save 时自动加解密。"""
    assert "sph_cookie" in settings._SECRET_CONFIG_KEYS


def test_sph_cookie_round_trip_through_load_save(tmp_path: Path, monkeypatch):
    """set_sph_cookie('plain') → save → load → 解密回 'plain'。"""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(settings._config_default()), encoding="utf-8")
    monkeypatch.setattr(settings, "get_config_path", lambda: str(cfg_file))

    new_cfg = {**settings._config_default(), "sph_cookie": "hy_source=web; hy_user=alice; hy_token=secret123"}
    settings.save_config(new_cfg)
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["sph_cookie"].startswith("enc:"), f"未加密：{on_disk['sph_cookie']!r}"

    loaded = settings.load_config()
    assert loaded["sph_cookie"] == "hy_source=web; hy_user=alice; hy_token=secret123"


def test_sph_config_module_level_cookie(monkeypatch, tmp_path):
    """sph_parser.config.SPH_COOKIE 必须从 settings 读，且 update_cookie 热更新模块变量。"""
    from server.sp_modules.sph_parser import config as sph_config
    import config.settings as settings
    import json

    # 隔离：把 config.json 重定向到 tmp_path，避免污染真实配置
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(settings._config_default()), encoding="utf-8")
    monkeypatch.setattr(settings, "get_config_path", lambda: str(cfg_file))

    # Spy: 记录 set_sph_cookie 调用
    calls = []
    real_set = settings.set_sph_cookie
    def spy_set(value, *, source="manual"):
        calls.append((value, source))
        return real_set(value, source=source)
    monkeypatch.setattr(settings, "set_sph_cookie", spy_set)

    monkeypatch.setattr(sph_config, "SPH_COOKIE", "")  # 重置
    # 模拟 settings.get_sph_cookie() 返回特定值
    monkeypatch.setattr(settings, "get_sph_cookie", lambda: "test-cookie")

    sph_config._init_from_settings()  # 显式触发初始化
    assert sph_config.get_cookie() == "test-cookie"

    sph_config.update_cookie("new-cookie")
    assert sph_config.get_cookie() == "new-cookie"
    # 验证持久化调用被正确触发
    assert calls == [("new-cookie", "manual")]
    # 验证落盘值已加密
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["sph_cookie"].startswith("enc:"), f"未加密：{on_disk['sph_cookie']!r}"
    assert on_disk["sph_cookie_source"] == "manual"

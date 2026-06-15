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

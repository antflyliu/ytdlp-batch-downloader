"""中英 i18n 词条一致性 + 完整性。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZH = ROOT / "frontend-vue/src/locales/zh.json"
EN = ROOT / "frontend-vue/src/locales/en.json"


def test_channels_group_exists_both_languages():
    zh = json.loads(ZH.read_text(encoding="utf-8"))
    en = json.loads(EN.read_text(encoding="utf-8"))
    assert "channels" in zh, "zh.json 缺 channels group"
    assert "channels" in en, "en.json 缺 channels group"


def test_channels_keys_identical():
    zh = json.loads(ZH.read_text(encoding="utf-8"))["channels"]
    en = json.loads(EN.read_text(encoding="utf-8"))["channels"]
    zh_keys = set(zh.keys())
    en_keys = set(en.keys())
    assert zh_keys == en_keys, (
        f"key 不一致：\n  zh 独有: {zh_keys - en_keys}\n  en 独有: {en_keys - zh_keys}"
    )


def test_channels_no_empty_value():
    zh = json.loads(ZH.read_text(encoding="utf-8"))["channels"]
    en = json.loads(EN.read_text(encoding="utf-8"))["channels"]
    for lang, m in [("zh", zh), ("en", en)]:
        empties = [k for k, v in m.items() if not v or not v.strip()]
        assert not empties, f"{lang}.channels 有空值: {empties}"


def test_channels_minimum_keys_count():
    """至少 49 个 key（与 Spec §4.7 对齐）。"""
    zh = json.loads(ZH.read_text(encoding="utf-8"))["channels"]
    assert len(zh) >= 49, f"channels key 数 {len(zh)} < 49"

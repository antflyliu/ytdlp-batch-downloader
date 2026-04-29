"""Every data-i18n / I18n.t key used under monitor_web must exist in en.json (dot paths).

Prevents EN locale from showing raw key paths like batchDownload.formatExcel.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "monitor_web"
EN_PATH = ROOT / "static" / "i18n" / "en.json"

KEY_PATTERN = re.compile(r'data-i18n(?:-placeholder)?=["\']([^"\']+)["\']')
T_PATTERN = re.compile(r"I18n\.t\(\s*['\"]([^'\"]+)['\"]")


def _get_path(data: dict, parts: list[str]):
    cur: object = data
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _collect_referenced_keys() -> set[str]:
    keys: set[str] = set()
    for p in list(ROOT.rglob("*.html")) + list(ROOT.rglob("*.js")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        keys.update(KEY_PATTERN.findall(text))
        keys.update(T_PATTERN.findall(text))
    return keys


@pytest.fixture(scope="module")
def en_data():
    return json.loads(EN_PATH.read_text(encoding="utf-8"))


def test_en_json_has_all_referenced_i18n_keys(en_data: dict):
    missing = []
    for k in sorted(_collect_referenced_keys()):
        parts = k.split(".")
        if _get_path(en_data, parts) is None:
            missing.append(k)
    assert not missing, "Missing keys in en.json:\n" + "\n".join(missing)

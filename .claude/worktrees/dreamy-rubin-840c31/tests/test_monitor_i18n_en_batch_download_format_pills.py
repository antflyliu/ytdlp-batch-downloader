"""Regression: Downloads page format pills use data-i18n=batchDownload.format*.

Missing keys in en.json caused raw key strings (e.g. batchDownload.formatExcel) in EN mode.
Expected: short labels Excel / CSV / TXT.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN_JSON = ROOT / "monitor_web" / "static" / "i18n" / "en.json"


def test_en_batch_download_has_format_pill_keys():
    data = json.loads(EN_JSON.read_text(encoding="utf-8"))
    bd = data.get("batchDownload", {})
    for key in ("formatExcel", "formatCsv", "formatTxt"):
        assert key in bd, f"en.json batchDownload.{key} must exist for index.html bd-pill labels"
        val = bd[key]
        assert isinstance(val, str) and val.strip(), f"batchDownload.{key} must be non-empty string"
        # Must not be the i18n path itself (fallback when key missing)
        assert val != f"batchDownload.{key}"
        assert not val.startswith("batchDownload.")


#!/usr/bin/env python3
"""Deep-merge i18n_en_overrides*.json into monitor_web/static/i18n/en.json."""
from __future__ import annotations

import json
from pathlib import Path


def deep_merge(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "monitor_web" / "static" / "i18n"
    en_path = root / "en.json"
    en = json.loads(en_path.read_text(encoding="utf-8"))
    for name in ("i18n_en_overrides.json", "i18n_en_overrides_b.json"):
        p = root / name
        if not p.exists():
            continue
        deep_merge(en, json.loads(p.read_text(encoding="utf-8")))
    en_path.write_text(json.dumps(en, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Merged into", en_path)


if __name__ == "__main__":
    main()

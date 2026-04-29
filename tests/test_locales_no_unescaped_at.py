"""
Regression test: verify literal @ characters use Vue I18n-safe syntax.

Vue I18n v9 (legacy: false) message compiler treats bare @ as the start of
a "linked message" token and throws "Invalid linked format" if the following
text doesn't form valid linked syntax. Literal @ must be written as a literal
interpolation expression: {'@'}.

Bug: "Invalid linked format" error in browser console when navigating
between pages because locale messages contained literal @ characters
(e.g. @handle, @BotFather, username@server).
"""

import json
from pathlib import Path

LOCALE_FILES = [
    "frontend-vue/src/locales/zh.json",
    "frontend-vue/src/locales/en.json",
]


def find_unescaped_at(text: str, key_path: str) -> list[str]:
    """Find @ characters not encoded as Vue I18n literal interpolation."""
    issues = []
    for pos, char in enumerate(text):
        if char != "@":
            continue
        is_literal_interpolation = (
            text[max(0, pos - 2):pos] == "{'"
            and text[pos + 1:pos + 3] == "'}"
        )
        if not is_literal_interpolation:
            context = text[max(0, pos - 10):pos + 15]
            issues.append(
                f"  {key_path}: ...{context}... "
                "(literal @ must be written as {'@'})"
            )
    return issues


def check_file(filepath: str) -> list[str]:
    issues = []
    data = json.loads(Path(filepath).read_text(encoding="utf-8"))

    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, str):
            issues.extend(find_unescaped_at(obj, path))

    walk(data)
    return issues


def test_no_unescaped_at_in_zh():
    root = Path(__file__).resolve().parent.parent
    issues = check_file(str(root / LOCALE_FILES[0]))
    assert not issues, (
        f"zh.json contains unescaped @ characters that will cause "
        f"Vue I18n 'Invalid linked format' errors:\n" + "\n".join(issues)
    )


def test_no_unescaped_at_in_en():
    root = Path(__file__).resolve().parent.parent
    issues = check_file(str(root / LOCALE_FILES[1]))
    assert not issues, (
        f"en.json contains unescaped @ characters that will cause "
        f"Vue I18n 'Invalid linked format' errors:\n" + "\n".join(issues)
    )

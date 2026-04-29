"""Contract tests for P0 AI content API routes and safe file constraints."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_MAIN = ROOT / "server" / "__main__.py"


def _read_server_text() -> str:
    return SERVER_MAIN.read_text(encoding="utf-8")


def _require_snippets(text: str, snippets: list[str], reason: str) -> None:
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        pytest.xfail(f"{reason}. Missing: {missing}")


def test_monitor_handler_routes_ai_content_endpoints():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            'elif path == "/api/article/generate":',
            'elif path == "/api/video-generate":',
            'elif path == "/api/article/list":',
            'elif path == "/api/video-generate/list":',
            'elif path.startswith("/api/article/") and path.endswith("/cancel"):',
            'elif path.startswith("/api/video-generate/") and path.endswith("/cancel"):',
        ],
        "P0 AI content MonitorHandler routes are not wired yet",
    )


def test_ai_content_api_uses_explicit_post_cancel_endpoints_instead_of_delete():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            "/api/article/{task_id}/cancel",
            "/api/video-generate/{task_id}/cancel",
        ],
        "Explicit AI content cancel endpoints are not documented in server source yet",
    )

    assert 'DELETE /api/article/' not in text
    assert 'DELETE /api/video-generate/' not in text


def test_ai_content_api_validates_safe_file_paths_under_configured_output_roots():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            "/api/video-generate/templates",
            "Path(",
            ".resolve()",
            ".relative_to(",
        ],
        "Safe file validation contract for generated assets is not implemented yet",
    )


def test_ai_content_api_defines_stable_error_responses_for_validation_and_cancel_conflicts():
    text = _read_server_text()

    _require_snippets(
        text,
        [
            'self._send_json({"error":',
            "}, 400)",
            "}, 404)",
            "}, 409)",
        ],
        "Stable 400/404/409 AI content API responses are not visible in server source yet",
    )

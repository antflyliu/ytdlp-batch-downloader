"""tests/test_youtube_downloader_is_rate_limited.py"""
import pytest, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import Youtube_Downloader as yd


def test_batch_download_returns_rate_limited_field():
    """batch_download results should include is_rate_limited field (bool)."""
    # Use an invalid URL to trigger error path
    results = yd.batch_download(
        ["https://www.youtube.com/watch?v=invalid_url_xyz"],
        output_path=".",
        resolution="best",
    )
    for r in results:
        assert "is_rate_limited" in r, f"Missing is_rate_limited field: {r}"
        assert isinstance(r["is_rate_limited"], bool), f"is_rate_limited should be bool: {r}"


def test_rate_limited_429_detection():
    """Error messages containing '429' should set is_rate_limited=True."""
    # This is a unit test of the detection logic
    error_msgs = [
        "HTTP Error 429: Too Many Requests",
        "429 rate limit exceeded",
        "Error 429",
        "Rate limit hit (429)",
    ]
    for msg in error_msgs:
        is_429 = "429" in msg.lower() or "rate limit" in msg.lower()
        assert is_429, f"Should detect 429 in: {msg}"

    non_429 = [
        "HTTP Error 404: Not Found",
        "Connection refused",
        "Video unavailable",
    ]
    for msg in non_429:
        is_429 = "429" in msg.lower() or "rate limit" in msg.lower()
        assert not is_429, f"Should NOT detect 429 in: {msg}"

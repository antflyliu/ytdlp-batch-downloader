from __future__ import annotations

from pathlib import Path

from monitor.article_source_archive import archive_article_source


def test_article_source_archive_localizes_media_and_reuses_existing_markdown(tmp_path):
    calls: list[str] = []

    def fake_downloader(url: str):
        calls.append(url)
        if url.endswith(".png"):
            return b"png", "image/png"
        if url.endswith(".mp3"):
            return b"mp3", "audio/mpeg"
        if url.endswith(".mp4"):
            return b"mp4", "video/mp4"
        if url.endswith(".pdf"):
            return b"pdf", "application/pdf"
        return b"bin", "application/octet-stream"

    result = archive_article_source(
        source_type="rss_item",
        source_id="rss-42",
        title="Source Title",
        source_url="https://example.com/posts/source",
        html_body=(
            "<article><p>Intro text.</p>"
            '<a href="/files/report.pdf">Report PDF</a>'
            '<img alt="cover" src="/cover.png">'
            '<audio src="https://cdn.example.com/audio.mp3"></audio>'
            "</article>"
        ),
        media=[{"url": "https://example.com/video.mp4", "mime_type": "video/mp4"}],
        root=tmp_path / "archive",
        downloader=fake_downloader,
    )

    markdown_path = Path(result.markdown_path)
    markdown = markdown_path.read_text(encoding="utf-8")

    assert markdown_path == tmp_path / "archive" / "rss_item" / "example.com" / "rss-42" / "source.md"
    assert "Intro text." in markdown
    assert "![cover](assets/asset-002.png)" in markdown
    assert "[Report PDF](assets/asset-001.pdf)" in markdown
    assert "[音频](assets/asset-003.mp3)" in markdown
    assert "[视频文件](assets/asset-004.mp4)" in markdown
    assert len(result.asset_paths) == 4

    reused = archive_article_source(
        source_type="rss_item",
        source_id="rss-42",
        title="Changed Title",
        source_url="https://example.com/posts/source",
        html_body="<p>Changed</p>",
        root=tmp_path / "archive",
        downloader=lambda _url: (_ for _ in ()).throw(AssertionError("must reuse local archive")),
    )

    assert reused.reused is True
    assert reused.markdown_text == markdown
    assert len(calls) == 4

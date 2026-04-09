"""Youtube_Downloader 代理顺序切换与直连兜底逻辑单元测试"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Youtube_Downloader import (
    batch_download,
    is_proxy_retryable_error,
    external_downloader_is_aria2,
    build_aria2_opts,
    proxy_url_uses_socks_scheme,
)


def test_proxy_url_uses_socks_scheme():
    assert proxy_url_uses_socks_scheme("socks5://u:p@h:1")
    assert proxy_url_uses_socks_scheme("SOCKS4://h:1080")
    assert not proxy_url_uses_socks_scheme("http://h:8080")
    assert not proxy_url_uses_socks_scheme(None)
    assert not proxy_url_uses_socks_scheme("")


def test_build_aria2_opts_skips_socks_all_proxy():
    o = build_aria2_opts("socks5://h:1")
    args = o.get("external_downloader_args") or []
    assert not any("all-proxy" in str(x) for x in args)


def test_external_downloader_is_aria2_variants():
    assert external_downloader_is_aria2({"external_downloader": "aria2c"})
    assert external_downloader_is_aria2({"external_downloader": "ARIA2C"})
    assert external_downloader_is_aria2({"external_downloader": r"C:\bin\aria2c.exe"})
    assert not external_downloader_is_aria2({})
    assert not external_downloader_is_aria2({"external_downloader": "ffmpeg"})


def test_is_proxy_retryable_detects_common_errors():
    assert is_proxy_retryable_error("Connection timed out")
    assert is_proxy_retryable_error("WinError 10054")
    assert is_proxy_retryable_error("远程主机强迫关闭了一个现有的连接")
    assert is_proxy_retryable_error("EOFError: 8 bytes missing")
    assert is_proxy_retryable_error("Invalid response version from server")
    assert not is_proxy_retryable_error("Video unavailable")
    assert not is_proxy_retryable_error("Private video")


@patch("Youtube_Downloader.yt_dlp.YoutubeDL")
def test_proxy_pool_sequential_then_direct_success(mock_ydl_cls):
    tmp = tempfile.mkdtemp()
    try:
        out_file = os.path.join(tmp, "t.mp4")
        proxies = ["http://p1:1", "http://p2:2"]

        instances = []

        def make_ctx(*args, **kwargs):
            inst = MagicMock()
            call_n = len(instances)
            instances.append(call_n)

            def extract_info(url, download=True):
                if call_n < 1:
                    raise Exception("timed out")
                return {"title": "t", "ext": "mp4", "_filename": out_file}

            inst.extract_info.side_effect = extract_info
            inst.prepare_filename.return_value = out_file
            return inst

        mock_ydl_cls.return_value.__enter__.side_effect = make_ctx
        mock_ydl_cls.return_value.__exit__.return_value = None

        open(out_file, "wb").close()

        results = batch_download(
            ["https://example.com/v"],
            tmp,
            "1080p",
            proxy_pool=proxies,
            no_subs=True,
            direct_fallback_after_proxies_exhausted=True,
        )
        assert results[0]["状态"] == "成功"
        assert "直连" in results[0]["信息"] or "http://p2" in results[0]["信息"]
        assert mock_ydl_cls.call_count >= 2
    finally:
        for root, dirs, files in os.walk(tmp, topdown=False):
            for f in files:
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except OSError:
                    pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass


@patch("Youtube_Downloader.yt_dlp.YoutubeDL")
def test_aria2_all_proxy_updates_each_proxy_attempt(mock_ydl_cls):
    tmp = tempfile.mkdtemp()
    out_file = os.path.join(tmp, "t.mp4")
    captured = []

    def make_instance(opts):
        captured.append(opts)
        inst = MagicMock()
        inst.__enter__.return_value = inst
        inst.__exit__.return_value = None

        def extract_info(url, download=True):
            # 第一次构造的 opts 对应首个代理，应失败并换下一个
            if len(captured) == 1:
                raise Exception("timed out")
            return {"title": "t", "ext": "mp4"}

        inst.extract_info.side_effect = extract_info
        inst.prepare_filename.return_value = out_file
        return inst

    mock_ydl_cls.side_effect = make_instance

    try:
        open(out_file, "wb").close()
        batch_download(
            ["https://x"],
            tmp,
            "1080p",
            proxy_pool=["http://a:1", "http://b:2"],
            no_subs=True,
            extra_ydl_opts=build_aria2_opts(None),
            direct_fallback_after_proxies_exhausted=False,
        )
        assert len(captured) >= 2
        args0 = captured[0].get("external_downloader_args") or []
        args1 = captured[1].get("external_downloader_args") or []
        assert any("--all-proxy=http://a:1" in x for x in args0)
        assert any("--all-proxy=http://b:2" in x for x in args1)
        assert captured[0].get("proxy") == "http://a:1"
        assert captured[1].get("proxy") == "http://b:2"
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass
        os.rmdir(tmp)


@patch("Youtube_Downloader.yt_dlp.YoutubeDL")
def test_aria2_disabled_for_socks_proxy_attempt(mock_ydl_cls):
    """SOCKS URL 不能传给 aria2c --all-proxy，batch_download 应去掉 external_downloader。"""
    tmp = tempfile.mkdtemp()
    out_file = os.path.join(tmp, "t.mp4")
    captured = []

    def make_instance(opts):
        captured.append(opts)
        inst = MagicMock()
        inst.__enter__.return_value = inst
        inst.__exit__.return_value = None

        def extract_info(url, download=True):
            if len(captured) == 1:
                raise Exception("timed out")
            return {"title": "t", "ext": "mp4"}

        inst.extract_info.side_effect = extract_info
        inst.prepare_filename.return_value = out_file
        return inst

    mock_ydl_cls.side_effect = make_instance

    try:
        open(out_file, "wb").close()
        batch_download(
            ["https://x"],
            tmp,
            "1080p",
            proxy_pool=["socks5://a:1", "http://b:2"],
            no_subs=True,
            extra_ydl_opts=build_aria2_opts(None),
            direct_fallback_after_proxies_exhausted=False,
        )
        assert len(captured) >= 2
        assert captured[0].get("external_downloader") is None
        assert captured[0].get("proxy") == "socks5://a:1"
        args1 = captured[1].get("external_downloader_args") or []
        assert any("--all-proxy=http://b:2" in x for x in args1)
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass
        os.rmdir(tmp)


@patch("Youtube_Downloader.yt_dlp.YoutubeDL")
def test_proxy_pool_dedupes_identical_urls(mock_ydl_cls):
    tmp = tempfile.mkdtemp()
    try:
        out_file = os.path.join(tmp, "t.mp4")
        same = "socks5://a:b@c:1"
        proxies = [same, same, "http://other:2"]

        n = [0]

        def make_ctx(*args, **kwargs):
            inst = MagicMock()

            def extract_info(url, download=True):
                n[0] += 1
                if n[0] < 2:
                    raise Exception("timeout")
                return {"title": "t", "ext": "mp4"}

            inst.extract_info.side_effect = extract_info
            inst.prepare_filename.return_value = out_file
            return inst

        mock_ydl_cls.return_value.__enter__.side_effect = make_ctx
        mock_ydl_cls.return_value.__exit__.return_value = None
        open(out_file, "wb").close()

        batch_download(
            ["https://example.com/v"],
            tmp,
            "1080p",
            proxy_pool=proxies,
            no_subs=True,
            direct_fallback_after_proxies_exhausted=False,
        )
        # 去重后仅 2 个代理尝试 + 无直连
        assert n[0] == 2
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass
        os.rmdir(tmp)

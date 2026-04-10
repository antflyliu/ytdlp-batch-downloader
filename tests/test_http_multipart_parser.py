"""Unit tests for the custom multipart/form-data parser."""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


def _build_multipart(parts: list[dict], boundary: str = "test-boundary") -> tuple[bytes, dict[str, str]]:
    chunks: list[bytes] = []
    for part in parts:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        disposition = f'Content-Disposition: form-data; name="{part["name"]}"'
        if part.get("filename") is not None:
            disposition += f'; filename="{part["filename"]}"'
        chunks.append((disposition + "\r\n").encode("utf-8"))
        if part.get("content_type"):
            chunks.append(f'Content-Type: {part["content_type"]}\r\n'.encode("utf-8"))
        chunks.append(b"\r\n")
        chunks.append(part["data"])
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }
    return body, headers


class TestHttpMultipartParser(unittest.TestCase):
    def test_read_single_file_part_extracts_expected_fields(self):
        from monitor.http_multipart import read_single_file_part

        body, headers = _build_multipart([{
            "name": "file",
            "filename": "urls.txt",
            "content_type": "text/plain",
            "data": b"https://youtube.com/watch?v=abc\n",
        }])

        part = read_single_file_part(io.BytesIO(body), headers, field_name="file")
        self.assertEqual(part.name, "file")
        self.assertEqual(part.filename, "urls.txt")
        self.assertEqual(part.content_type, "text/plain")
        self.assertEqual(part.data, b"https://youtube.com/watch?v=abc\n")

    def test_read_single_file_part_raises_when_boundary_missing(self):
        from monitor.http_multipart import MultipartParseError, read_single_file_part

        headers = {"Content-Type": "multipart/form-data", "Content-Length": "4"}
        with self.assertRaises(MultipartParseError):
            read_single_file_part(io.BytesIO(b"test"), headers)

    def test_read_single_file_part_raises_when_target_field_missing(self):
        from monitor.http_multipart import MultipartParseError, read_single_file_part

        body, headers = _build_multipart([{
            "name": "meta",
            "filename": None,
            "content_type": "text/plain",
            "data": b"hello",
        }])

        with self.assertRaises(MultipartParseError):
            read_single_file_part(io.BytesIO(body), headers, field_name="file")

    def test_parser_supports_filename_star(self):
        from monitor.http_multipart import parse_multipart_form_data

        boundary = "utf8-boundary"
        body = (
            b"--utf8-boundary\r\n"
            b"Content-Disposition: form-data; name=\"file\"; filename*=UTF-8''%E6%B5%8B%E8%AF%95.txt\r\n"
            b"Content-Type: text/plain\r\n\r\n"
            b"payload\r\n"
            b"--utf8-boundary--\r\n"
        )

        parts = parse_multipart_form_data(body, boundary.encode("utf-8"))
        self.assertEqual(parts[0].filename, "测试.txt")


if __name__ == "__main__":
    unittest.main()

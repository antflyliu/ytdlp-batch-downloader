"""Minimal multipart/form-data parsing helpers for the built-in HTTP server."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import unquote
import re

_BOUNDARY_RE = re.compile(r'boundary=(?:"([^"]+)"|([^;]+))', re.IGNORECASE)


class MultipartParseError(ValueError):
    """Raised when multipart/form-data parsing fails."""


@dataclass(slots=True)
class MultipartPart:
    name: str
    filename: str | None
    content_type: str | None
    headers: dict[str, str]
    data: bytes


def _header_get(headers: Mapping[str, str] | object, name: str) -> str:
    getter = getattr(headers, "get", None)
    if callable(getter):
        return str(getter(name, "") or "")
    return str(getattr(headers, name, "") or "")


def _extract_boundary(content_type: str) -> bytes:
    match = _BOUNDARY_RE.search(content_type or "")
    if not match:
        raise MultipartParseError("缺少 multipart boundary")
    boundary = (match.group(1) or match.group(2) or "").strip()
    if not boundary:
        raise MultipartParseError("multipart boundary 为空")
    return boundary.encode("utf-8")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def _parse_content_disposition(value: str) -> tuple[str | None, str | None]:
    field_name: str | None = None
    filename: str | None = None
    for item in value.split(";")[1:]:
        item = item.strip()
        if "=" not in item:
            continue
        key, raw = item.split("=", 1)
        key = key.strip().lower()
        raw = raw.strip()
        if key == "name":
            field_name = _strip_quotes(raw)
        elif key == "filename":
            filename = _strip_quotes(raw)
        elif key == "filename*":
            decoded = _strip_quotes(raw)
            if "''" in decoded:
                _, encoded_name = decoded.split("''", 1)
                filename = unquote(encoded_name)
            else:
                filename = unquote(decoded)
    return field_name, filename


def parse_multipart_form_data(body: bytes, boundary: bytes) -> list[MultipartPart]:
    if not boundary:
        raise MultipartParseError("multipart boundary 为空")

    delimiter = b"--" + boundary
    parts: list[MultipartPart] = []

    for chunk in body.split(delimiter):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if not chunk or chunk == b"--":
            continue
        if chunk.endswith(b"--"):
            chunk = chunk[:-2].rstrip(b"\r\n")
        header_blob, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            raise MultipartParseError("multipart part 缺少 header/body 分隔")
        if data.endswith(b"\r\n"):
            data = data[:-2]

        headers: dict[str, str] = {}
        for line in header_blob.split(b"\r\n"):
            try:
                decoded = line.decode("utf-8")
            except UnicodeDecodeError:
                decoded = line.decode("latin-1")
            if ":" not in decoded:
                raise MultipartParseError("multipart part header 格式非法")
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()

        disposition = headers.get("content-disposition", "")
        field_name, filename = _parse_content_disposition(disposition)
        if not field_name:
            raise MultipartParseError("multipart part 缺少字段名")

        parts.append(MultipartPart(
            name=field_name,
            filename=filename,
            content_type=headers.get("content-type"),
            headers=headers,
            data=data,
        ))

    return parts


def read_multipart_parts(
    rfile,
    headers,
    *,
    max_bytes: int = 20 * 1024 * 1024,
) -> list[MultipartPart]:
    content_type = _header_get(headers, "Content-Type")
    boundary = _extract_boundary(content_type)
    content_length_raw = _header_get(headers, "Content-Length")
    try:
        content_length = int(content_length_raw or "0")
    except ValueError as ex:
        raise MultipartParseError("Content-Length 非法") from ex
    if content_length <= 0:
        raise MultipartParseError("上传请求体为空")
    if content_length > max_bytes:
        raise MultipartParseError(f"上传文件过大（限制 {max_bytes // (1024 * 1024)}MB）")

    body = rfile.read(content_length)
    if len(body) != content_length:
        raise MultipartParseError("上传请求体长度不完整")
    return parse_multipart_form_data(body, boundary)


def read_single_file_part(
    rfile,
    headers,
    *,
    field_name: str = "file",
    max_bytes: int = 20 * 1024 * 1024,
) -> MultipartPart:
    parts = read_multipart_parts(rfile, headers, max_bytes=max_bytes)
    for part in parts:
        if part.name == field_name:
            return part
    raise MultipartParseError("未上传文件")

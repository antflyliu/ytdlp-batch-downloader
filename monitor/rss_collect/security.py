from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def validate_external_http_url(value: str) -> str:
    text = (value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("RSS 地址必须是 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("RSS 地址不能包含用户名或密码")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("RSS 地址缺少主机名")
    if host in {"0.0.0.0", "::"}:
        raise ValueError("RSS 地址不能指向无效主机")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("RSS 地址不能指向内网、本机或保留地址")
    try:
        ip = ipaddress.ip_address(host)
        if _blocked_ip(ip):
            raise ValueError("RSS 地址不能指向内网、本机或保留地址")
        return text
    except ValueError as exc:
        if "内网" in str(exc):
            raise

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return text
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _blocked_ip(ip):
            raise ValueError("RSS 地址解析到了内网、本机或保留地址")
    return text


def validate_external_ip_address(value: str) -> None:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("RSS 地址连接到了无效 IP") from exc
    if _blocked_ip(ip):
        raise ValueError("RSS 地址连接到了内网、本机或保留地址")


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_private
        or ip.is_reserved
        or ip.is_unspecified
    )

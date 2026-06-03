from __future__ import annotations

import ipaddress
import socket

ALLOWED_MAIL_SECURITY = {"ssl", "starttls"}
IMAP_PORTS = {143, 993}
SMTP_PORTS = {465, 587}
BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def validate_mail_endpoint(host: str | None, port: int | None, security: str | None, *, service: str) -> None:
    hostname = str(host or "").strip()
    if not hostname:
        return
    if "://" in hostname or "/" in hostname or "\\" in hostname:
        raise ValueError(f"{service} host must be a hostname or IP address")
    normalized_host = hostname.rstrip(".").lower()
    if normalized_host in BLOCKED_HOSTNAMES:
        raise ValueError(f"{service} host is not allowed")
    mode = str(security or "ssl").strip().lower()
    if mode not in ALLOWED_MAIL_SECURITY:
        raise ValueError(f"{service} security must be ssl or starttls")
    try:
        parsed_port = int(port or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{service} port is invalid") from exc
    allowed_ports = IMAP_PORTS if service == "imap" else SMTP_PORTS
    if parsed_port not in allowed_ports:
        allowed = ", ".join(str(item) for item in sorted(allowed_ports))
        raise ValueError(f"{service} port must be one of: {allowed}")
    _reject_blocked_ip_literal(normalized_host, service)
    _reject_blocked_dns_targets(hostname, parsed_port, service)


def _reject_blocked_ip_literal(hostname: str, service: str) -> None:
    literal = hostname.strip("[]")
    try:
        ip = ipaddress.ip_address(literal)
    except ValueError:
        return
    _reject_blocked_ip(ip, service)


def _reject_blocked_dns_targets(hostname: str, port: int, service: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"{service} host could not be resolved") from exc
    if not addresses:
        raise ValueError(f"{service} host could not be resolved")
    for _, _, _, _, sockaddr in addresses:
        _reject_blocked_ip(ipaddress.ip_address(sockaddr[0]), service)


def _reject_blocked_ip(ip: ipaddress._BaseAddress, service: str) -> None:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(f"{service} host resolves to a blocked address")

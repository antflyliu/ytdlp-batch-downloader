from __future__ import annotations

import logging
from dataclasses import asdict
from ipaddress import ip_address

from monitor.proxy_router import CanonicalProxyCandidate

_log = logging.getLogger(__name__)


class TemplateFetcher:
    """模板型 provider API 执行器（Task 4 skeleton）"""

    def __init__(self, config: dict):
        self.config = config or {}

    def build_request(self, page: int = 1, **overrides) -> dict:
        base_url = (self.config.get("base_url") or "").rstrip("/")
        list_path = self.config.get("list_path") or ""
        method = (self.config.get("method") or "GET").upper()
        auth = self.config.get("auth") or {}
        query_defaults = dict(self.config.get("query_defaults") or {})
        pagination = self.config.get("pagination") or {}

        params = {**query_defaults}
        page_param = pagination.get("page_param")
        if page_param:
            params[page_param] = page

        headers = {}
        if auth.get("type") == "bearer" and auth.get("token"):
            headers["Authorization"] = f"Bearer {auth['token']}"

        request = {
            "method": method,
            "url": f"{base_url}{list_path}",
            "params": params,
            "headers": headers,
        }
        request.update(overrides)
        return request


def extract_items(raw: dict, response_config: dict) -> list[dict]:
    items_path = (response_config or {}).get("items_path")
    if not items_path:
        return []

    current = raw
    for part in items_path.split("."):
        if not isinstance(current, dict):
            return []
        current = current.get(part)
    return current if isinstance(current, list) else []


def _pick_value(item: dict, paths: list[str] | None):
    if not paths:
        return None
    for path in paths:
        value = item.get(path)
        if value is not None:
            return value
    return None


def _select_protocol(value, protocol_order: list[str]) -> str | None:
    if isinstance(value, list):
        normalized = [str(v).lower() for v in value]
        for preferred in protocol_order:
            if preferred in normalized:
                return preferred
        return normalized[0] if normalized else None
    if value is None:
        return None
    return str(value).lower()


def _is_private_host(host: str) -> bool:
    try:
        addr = ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified
    except ValueError:
        return host in {"localhost"}


def normalize_item(item: dict, config: dict) -> CanonicalProxyCandidate | None:
    field_mapping = config.get("field_mapping") or {}
    protocol_order = config.get("protocol_order") or ["http", "https", "socks5"]

    host = _pick_value(item, field_mapping.get("host"))
    port = _pick_value(item, field_mapping.get("port"))
    protocol_paths = field_mapping.get("protocol")
    raw_protocol = _pick_value(item, protocol_paths)
    protocol = _select_protocol(raw_protocol, protocol_order)
    if _log.isEnabledFor(logging.DEBUG):
        _log.debug(
            "normalize_item protocol: paths=%r raw=%r selected=%r host=%r",
            protocol_paths,
            raw_protocol,
            protocol,
            host,
        )
    username = _pick_value(item, field_mapping.get("username"))
    password = _pick_value(item, field_mapping.get("password"))
    country_code = _pick_value(item, field_mapping.get("country_code"))

    if not host or port is None or not protocol:
        return None

    host = str(host)
    if _is_private_host(host):
        return None

    try:
        port = int(port)
    except (TypeError, ValueError):
        return None

    if not (1 <= port <= 65535):
        return None

    if username and password:
        proxy_url = f"{protocol}://{username}:{password}@{host}:{port}"
    else:
        proxy_url = f"{protocol}://{host}:{port}"

    return CanonicalProxyCandidate(
        candidate_key=f"{config.get('provider_id', 0)}:{protocol}:{host}:{port}:{username or ''}",
        provider_id=config.get("provider_id", 0),
        provider_name=config.get("provider_name", ""),
        provider_adapter=config.get("provider_adapter", "list_api"),
        protocol=protocol,
        host=host,
        port=port,
        proxy_url=proxy_url,
        username=username,
        country_code=country_code,
    )


def fetch_provider_candidates(provider: dict, scenario: dict) -> list[CanonicalProxyCandidate]:
    cfg = provider.get("config_json") or {}
    response_cfg = cfg.get("response") or {}

    if cfg.get("mode") == "custom" and cfg.get("adapter_name"):
        from monitor.provider_adapters import get_adapter

        adapter = get_adapter(cfg.get("adapter_name"), cfg)
        if adapter is None:
            return []
        raw_response = adapter.fetch_page(1)
        items = adapter.extract_items(raw_response)
    else:
        raw_response = scenario.get("raw_response") or {}
        items = extract_items(raw_response, response_cfg)

    normalized = []
    normalize_cfg = {
        "field_mapping": response_cfg.get("field_mapping") or {},
        "protocol_order": scenario.get("protocol_order") or ["http", "https", "socks5"],
        "provider_id": provider.get("id", 0),
        "provider_name": provider.get("name", ""),
        "provider_adapter": provider.get("adapter_type", "list_api"),
    }

    for item in items:
        candidate = normalize_item(item, normalize_cfg)
        if candidate is not None:
            normalized.append(candidate)

    return normalized

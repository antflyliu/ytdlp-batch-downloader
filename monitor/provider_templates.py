from __future__ import annotations

import logging
from ipaddress import ip_address

import requests

from monitor.db import DEFAULT_PROXY_PROTOCOL_ORDER
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
    protocol_order = config.get("protocol_order") or list(DEFAULT_PROXY_PROTOCOL_ORDER)

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


def _effective_response_config(cfg: dict) -> dict:
    """
    合并 UI 持久化的顶层字段与可选的 response 子对象。

    页面表单把 items_path、field_mapping 写在 config_json 根上；
    部分测试/手工配置使用 config_json.response，两者应等价生效。
    """
    nested = dict(cfg.get("response") or {})
    if cfg.get("items_path") and not nested.get("items_path"):
        nested["items_path"] = cfg["items_path"]
    if cfg.get("field_mapping") and not nested.get("field_mapping"):
        nested["field_mapping"] = cfg["field_mapping"]
    return nested


def _resolve_adapter_name(cfg: dict) -> str | None:
    """
    解析内置适配器名称（仅来自 config_json，不做 URL 猜测）。

    - 非空 ``adapter_name``：在 ``provider_adapters`` 注册表中查找并实例化。
    - 空值：``list_api`` / ``public_feed`` 走通用 ``requests`` GET + ``items_path`` 解析。

    可选遗留字段 ``mode == \"custom\"`` 仅作文档语义；拉取逻辑只认 ``adapter_name``。
    """
    name = (cfg.get("adapter_name") or "").strip()
    return name.lower() if name else None


def _fetch_generic_list_api_json(cfg: dict) -> dict:
    """
    对「列表 API / 公共订阅」类配置发起一次 GET，返回 JSON。

    仅附带 UI 中已有的 limit / country / protocol 与 page，避免向未知 API 注入
    Geonode 专有参数。    需 Geonode 完整查询参数时，请在配置中设置 ``adapter_name: geonode``（见 Web 表单「列表解析适配器」）。
    """
    url = (cfg.get("base_url") or "").strip()
    if not url:
        return {}
    params: dict[str, object] = {"page": 1}
    lim = cfg.get("limit")
    if lim is not None:
        try:
            params["limit"] = int(lim)
        except (TypeError, ValueError):
            params["limit"] = lim
    if cfg.get("country"):
        params["country"] = cfg["country"]
    if cfg.get("protocol"):
        params["protocols"] = cfg["protocol"]
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; ytdlp-monitor/1.0)",
    }
    try:
        resp = requests.get(url, params=params, timeout=25, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _log.warning("list API GET failed: %s", exc)
        return {}


def fetch_provider_candidates(provider: dict, scenario: dict) -> list[CanonicalProxyCandidate]:
    cfg = provider.get("config_json") or {}
    response_cfg = _effective_response_config(cfg)
    adapter_type = provider.get("adapter_type") or ""

    from monitor.provider_adapters import get_adapter

    adapter_name = _resolve_adapter_name(cfg)
    adapter = get_adapter(adapter_name, cfg) if adapter_name else None

    if adapter is not None:
        raw_response = adapter.fetch_page(1)
        items = adapter.extract_items(raw_response)
    elif adapter_type in ("list_api", "public_feed") and (cfg.get("base_url") or "").strip():
        raw_response = _fetch_generic_list_api_json(cfg)
        items = extract_items(raw_response, response_cfg)
    else:
        raw_response = scenario.get("raw_response") or {}
        items = extract_items(raw_response, response_cfg)

    normalized = []
    normalize_cfg = {
        "field_mapping": response_cfg.get("field_mapping") or {},
        "protocol_order": scenario.get("protocol_order") or list(DEFAULT_PROXY_PROTOCOL_ORDER),
        "provider_id": provider.get("id", 0),
        "provider_name": provider.get("name", ""),
        "provider_adapter": provider.get("adapter_type", "list_api"),
    }

    for item in items:
        candidate = normalize_item(item, normalize_cfg)
        if candidate is not None:
            normalized.append(candidate)

    return normalized

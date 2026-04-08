from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_build_request_get_bearer_auth_and_pagination():
    from monitor.provider_templates import TemplateFetcher

    fetcher = TemplateFetcher(
        {
            "mode": "template",
            "base_url": "https://api.example.com",
            "list_path": "/proxies",
            "method": "GET",
            "auth": {"type": "bearer", "token": "test-token"},
            "query_defaults": {"limit": 50},
            "pagination": {
                "type": "page",
                "page_param": "page",
                "page_size_param": "limit",
            },
        }
    )

    req = fetcher.build_request(page=2)

    assert req["method"] == "GET"
    assert req["url"] == "https://api.example.com/proxies"
    assert req["params"]["limit"] == 50
    assert req["params"]["page"] == 2
    assert req["headers"]["Authorization"] == "Bearer test-token"


def test_extract_items_with_simple_items_path():
    from monitor.provider_templates import extract_items

    raw = {"data": [{"ip": "1.2.3.4", "port": 8080}]}

    items = extract_items(raw, {"items_path": "data"})

    assert len(items) == 1
    assert items[0]["ip"] == "1.2.3.4"


def test_normalize_item_geonode_style_prefers_protocol_order():
    from monitor.provider_templates import normalize_item

    item = {
        "ip": "8.8.8.8",
        "port": 3128,
        "protocols": ["socks5", "http"],
        "country": "US",
        "username": "u1",
        "password": "p1",
    }

    result = normalize_item(
        item,
        {
            "field_mapping": {
                "host": ["ip", "host"],
                "port": ["port"],
                "protocol": ["protocols", "protocol"],
                "username": ["username"],
                "password": ["password"],
                "country_code": ["country"],
            },
            "protocol_order": ["http", "https", "socks5"],
            "provider_id": 1,
            "provider_name": "GeoNode",
            "provider_adapter": "list_api",
        },
    )

    assert result is not None
    assert result.host == "8.8.8.8"
    assert result.port == 3128
    assert result.protocol == "http"
    assert result.country_code == "US"


def test_normalize_item_drops_invalid_private_host():
    from monitor.provider_templates import normalize_item

    item = {"ip": "127.0.0.1", "port": 8080}

    result = normalize_item(
        item,
        {
            "field_mapping": {
                "host": ["ip"],
                "port": ["port"],
            },
            "provider_id": 1,
            "provider_name": "BadProvider",
            "provider_adapter": "list_api",
        },
    )

    assert result is None


def test_fetch_provider_candidates_uses_registered_custom_adapter(monkeypatch):
    from monitor.provider_adapters import register_adapter
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter
    from monitor.provider_templates import fetch_provider_candidates

    class FakeGeonodeAdapter(GeonodeAdapter):
        def fetch_page(self, page: int) -> dict:
            return {"data": [{"ip": "8.8.8.8", "port": 8080, "protocol": "http"}]}

    register_adapter("geonode", FakeGeonodeAdapter)

    provider = {
        "id": 10,
        "name": "GeoNode Custom",
        "adapter_type": "list_api",
        "config_json": {
            "mode": "custom",
            "adapter_name": "geonode",
            "response": {
                "field_mapping": {
                    "host": ["ip"],
                    "port": ["port"],
                    "protocol": ["protocol"],
                },
            },
        },
    }

    candidates = fetch_provider_candidates(provider, {"protocol_order": ["http", "https", "socks5"]})

    assert len(candidates) == 1
    assert candidates[0].host == "8.8.8.8"
    assert candidates[0].protocol == "http"



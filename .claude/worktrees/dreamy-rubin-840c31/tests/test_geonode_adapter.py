from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_adapter_registry_returns_registered_geonode_adapter():
    from monitor.provider_adapters import get_adapter, register_adapter
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    register_adapter("geonode", GeonodeAdapter)

    adapter = get_adapter("geonode", {"base_url": "https://proxylist.geonode.com"})

    assert isinstance(adapter, GeonodeAdapter)


def test_geonode_adapter_fetch_page_respects_limit_override():
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    calls = []

    class FakeTransport:
        def fetch_json(self, url: str, params: dict | None = None):
            calls.append((url, params))
            return {"data": []}

    adapter = GeonodeAdapter(
        {
            "base_url": "https://proxylist.geonode.com",
            "limit": 20,
        },
        transport=FakeTransport(),
    )

    adapter.fetch_page(4)

    assert calls == [
        (
            "https://proxylist.geonode.com",
            {"page": 4, "limit": 20, "sort_by": "lastChecked", "speed": "fast", "sort_type": "desc"},
        ),
    ]


def test_geonode_adapter_extract_items_handles_missing_data():
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    adapter = GeonodeAdapter({"base_url": "https://proxylist.geonode.com"})

    result = adapter.extract_items({})
    assert result == []

    result = adapter.extract_items({"data": None})
    assert result == []

    result = adapter.extract_items({"data": {"ip": "1.2.3.4"}})
    assert result == []


def test_geonode_adapter_extract_items_handles_non_list_data():
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    adapter = GeonodeAdapter({"base_url": "https://proxylist.geonode.com"})

    result = adapter.extract_items({"data": {"ip": "1.2.3.4"}})
    assert result == []

    result = adapter.extract_items({"data": "not a list"})
    assert result == []

    result = adapter.extract_items({"data": 123})
    assert result == []


def test_geonode_adapter_extract_items_returns_list_when_valid():
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    adapter = GeonodeAdapter({"base_url": "https://proxylist.geonode.com"})
    raw = {"data": [{"ip": "1.2.3.4", "port": 8080, "protocol": "http"}]}

    result = adapter.extract_items(raw)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["ip"] == "1.2.3.4"


def test_geonode_adapter_fetch_page_skips_transport_when_base_url_missing():
    """When base_url is absent from config, fetch_page returns empty data without calling transport."""
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    calls = []

    class FakeTransport:
        def fetch_json(self, url: str, params: dict | None = None):
            calls.append((url, params))
            return {"data": []}

    adapter = GeonodeAdapter({}, transport=FakeTransport())

    result = adapter.fetch_page(1)

    assert calls == []
    assert result == {"data": []}

def test_geonode_adapter_fetch_page_skips_transport_when_base_url_empty():
    """When base_url is empty string, fetch_page returns empty data without calling transport."""
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    calls = []

    class FakeTransport:
        def fetch_json(self, url: str, params: dict | None = None):
            calls.append((url, params))
            return {"data": []}

    adapter = GeonodeAdapter({"base_url": ""}, transport=FakeTransport())

    result = adapter.fetch_page(1)

    assert calls == []
    assert result == {"data": []}



def test_geonode_adapter_fetch_page_uses_builtin_http_fallback_when_transport_missing(monkeypatch):
    from monitor.provider_adapters.geonode_adapter import GeonodeAdapter

    calls = []

    def fake_fetch_json(self, url: str, params: dict | None = None):
        calls.append((url, params))
        return {"data": [{"ip": "8.8.8.8", "port": 8080, "protocols": ["http"]}]}

    monkeypatch.setattr(GeonodeAdapter, "_fetch_json", fake_fetch_json)

    adapter = GeonodeAdapter({
        "base_url": "https://proxylist.geonode.com/api/proxy-list",
        "limit": 50,
    })

    result = adapter.fetch_page(1)

    assert calls == [
        (
            "https://proxylist.geonode.com/api/proxy-list",
            {"page": 1, "limit": 50, "sort_by": "lastChecked", "speed": "fast", "sort_type": "desc"},
        )
    ]
    assert result["data"][0]["ip"] == "8.8.8.8"

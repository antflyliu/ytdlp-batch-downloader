ADAPTER_REGISTRY = {}


def register_adapter(name, cls):
    ADAPTER_REGISTRY[name] = cls


def get_adapter(name: str, config: dict):
    cls = ADAPTER_REGISTRY.get(name)
    return cls(config) if cls else None


# Auto-register built-in adapters
from monitor.provider_adapters.geonode_adapter import GeonodeAdapter
register_adapter("geonode", GeonodeAdapter)

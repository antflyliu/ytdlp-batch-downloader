import httpx


class GeonodeAdapter:
    """Geonode 专属 adapter（当前仅实现最小提取逻辑）"""

    def __init__(self, config: dict, transport=None):
        self.config = config or {}
        self._transport = transport

    def _fetch_json(self, url: str, params: dict | None = None) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        with httpx.Client(timeout=15, headers=headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def fetch_page(self, page: int) -> dict:
        base_url = (self.config.get("base_url") or "").rstrip("/")
        if not base_url:
            return {"data": []}
        page_param = self.config.get("page_param") or "page"
        params = {
            page_param: page,
            "limit": self.config.get("limit", 50),
            "sort_by": self.config.get("sort_by", "lastChecked"),
            "speed": self.config.get("speed", "fast"),
            "sort_type": self.config.get("sort_type", "desc"),
        }
        if self.config.get("country"):
            params["country"] = self.config["country"]
        if self.config.get("protocol"):
            params["protocols"] = self.config.get("protocol", "http%2Chttps%2Csocks5")
        if self._transport is not None:
            return self._transport.fetch_json(base_url, params=params)
        return self._fetch_json(base_url, params=params)

    def extract_items(self, raw: dict) -> list[dict]:
        data = raw.get("data") if isinstance(raw, dict) else None
        return data if isinstance(data, list) else []


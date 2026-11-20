"""Keitaro Admin API client.

Auth is the Api-Key header. PUT updates only the fields we send, so publishing
a stream sends a new offers list and leaves filters and the redirect URL alone.
"""

import time

import httpx

from app.config import Settings


class KeitaroError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def api_root(base_url: str) -> str:
    url = base_url.rstrip("/")
    suffix = "/admin_api/v1"
    if url.endswith(suffix):
        return url
    return url + suffix


class KeitaroClient:
    def __init__(self, settings: Settings, timeout: float = 20.0):
        self._settings = settings
        self._root = api_root(settings.keitaro_base_url)
        self._timeout = timeout
        self._offers: list[dict] | None = None
        self._offers_at = 0.0

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def list_campaigns(self) -> list[dict]:
        return self._as_list(self._request("GET", "/campaigns"))

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json=payload)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    def get_streams(self, campaign_id: int) -> list[dict]:
        return self._as_list(self._request("GET", f"/campaigns/{campaign_id}/streams"))

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)

    def get_offer(self, offer_id: int) -> dict:
        offer = self._request("GET", f"/offers/{offer_id}")
        self._remember_offer(offer)
        return offer

    def list_offers(self) -> list[dict]:
        now = time.monotonic()
        if self._offers is not None and now - self._offers_at < 30:
            return self._offers
        offers = self._as_list(self._request("GET", "/offers"))
        self._offers = offers
        self._offers_at = now
        return offers

    def search_offers(self, query: str, limit: int = 20) -> list[dict]:
        needle = query.strip().lower()
        if not needle:
            return []
        scored: list[tuple[int, int, dict]] = []
        for offer in self.list_offers():
            if offer.get("state") == "deleted":
                continue
            name = str(offer.get("name") or "")
            offer_id = offer.get("id")
            if offer_id is None:
                continue
            token = str(offer_id)
            if token == needle:
                rank = 0
            elif name.lower().startswith(needle) or token.startswith(needle):
                rank = 1
            elif needle in name.lower():
                rank = 2
            else:
                continue
            scored.append((rank, int(offer_id), {"id": int(offer_id), "name": name}))
        scored.sort()
        return [item for _, _, item in scored[:limit]]

    def list_domains(self) -> list[dict]:
        return self._as_list(self._request("GET", "/domains"))

    def list_groups(self, group_type: str) -> list[dict]:
        return self._as_list(self._request("GET", "/groups", params={"type": group_type}))

    def list_traffic_sources(self) -> list[dict]:
        return self._as_list(self._request("GET", "/traffic_sources"))

    def _remember_offer(self, offer: dict) -> None:
        if self._offers is None or offer.get("id") is None:
            return
        self._offers = [item for item in self._offers if item.get("id") != offer["id"]]
        self._offers.append(offer)

    def _request(self, method: str, path: str, json: dict | None = None, params: dict | None = None):
        if not self._settings.keitaro_api_key:
            raise KeitaroError(0, "В .env не задан KEITARO_API_KEY")
        try:
            with httpx.Client(timeout=self._timeout, trust_env=False) as http:
                response = http.request(
                    method,
                    self._root + path,
                    headers={
                        "Api-Key": self._settings.keitaro_api_key,
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=json,
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise KeitaroError(0, f"Нет связи с Keitaro: {exc}") from exc
        if response.status_code >= 400:
            raise KeitaroError(response.status_code, _error_text(response))
        if not response.content:
            return {}
        return response.json()

    @staticmethod
    def _as_list(payload) -> list[dict]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("rows", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    if isinstance(body, dict):
        for key in ("error", "message", "description"):
            if body.get(key):
                return str(body[key])
        return str(body)
    text = str(body).strip()
    return text[:500] or f"Keitaro ответил {response.status_code}"

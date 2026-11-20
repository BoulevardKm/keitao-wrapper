"""Create a Keitaro campaign with the two flows from the assignment.

Flow 1 is checked first (rotation by position). It accepts the given country
codes and redirects them to Google. Flow 2 has no filter, so it receives
everyone else and sends them to the chosen offer.
"""

import re
import secrets

from app.config import Settings
from app.errors import AppError
from app.keitaro import KeitaroClient, KeitaroError


def parse_geos(raw: str) -> list[str]:
    codes: list[str] = []
    for part in re.split(r"[\s,;]+", raw.strip()):
        if not part:
            continue
        code = part.upper()
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise AppError(f"Некорректный гео-код «{part}». Нужен код страны из двух букв, например AU.")
        if code not in codes:
            codes.append(code)
    if not codes:
        raise AppError("Укажите хотя бы одну страну.")
    return codes


def build_campaign_payload(name: str, domain_id: int, group_id: int, source_id: int, alias: str = "") -> dict:
    return {
        "name": name,
        "alias": alias,
        "type": "position",
        "state": "active",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
        "group_id": group_id,
        "traffic_source_id": source_id,
        "domain_id": domain_id,
        "parameters": {
            "cost": {"name": "cost", "placeholder": "", "alias": ""},
        },
    }


def build_google_stream(campaign_id: int, countries: list[str], safe_url: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Flow 1",
        "position": 1,
        "schema": "redirect",
        "action_type": "http",
        "action_payload": safe_url,
        "state": "active",
        "collect_clicks": True,
        "filter_or": False,
        "filters": [
            {"name": "country", "mode": "accept", "payload": list(countries)},
        ],
        "triggers": [],
        "landings": [],
        "offers": [],
    }


def build_offer_stream(campaign_id: int, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Flow 2",
        "position": 2,
        "schema": "landings",
        "action_type": "http",
        "action_payload": "",
        "state": "active",
        "collect_clicks": True,
        "filter_or": False,
        "filters": [],
        "triggers": [],
        "landings": [],
        "offers": [
            {"offer_id": offer_id, "share": 100, "state": "active"},
        ],
    }


def _host(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"^https?://", "", text)
    return text.strip("/")


class CampaignCreator:
    def __init__(self, client: KeitaroClient, settings: Settings):
        self.client = client
        self.settings = settings

    def create(self, name: str, geo_raw: str, offer_id: int) -> dict:
        title = name.strip()
        if not title:
            raise AppError("Укажите название кампании.")
        if offer_id <= 0:
            raise AppError("Выберите оффер.")
        countries = parse_geos(geo_raw)
        offer = self.client.get_offer(offer_id)
        if offer.get("state") == "deleted":
            raise AppError(f"Оффер {offer_id} удалён в Keitaro.")

        domain = _find_domain(self.client.list_domains(), self.settings.keitaro_domain)
        group = _find_named(self.client.list_groups("campaigns"), self.settings.keitaro_group, "группа кампаний")
        source = _find_named(self.client.list_traffic_sources(), self.settings.keitaro_source, "источник")

        payload = build_campaign_payload(title, int(domain["id"]), int(group["id"]), int(source["id"]))
        campaign = self._create_campaign(payload)
        campaign_id = int(campaign["id"])
        try:
            self.client.create_stream(build_google_stream(campaign_id, countries, self.settings.keitaro_safe_url))
            self.client.create_stream(build_offer_stream(campaign_id, offer_id))
        except KeitaroError as exc:
            try:
                self.client.delete_campaign(campaign_id)
            except KeitaroError:
                raise AppError(f"Кампания {campaign_id} создана, но один из потоков не собрался: {exc}") from exc
            raise AppError(f"Не удалось собрать потоки, кампания удалена. Ответ Keitaro: {exc}") from exc
        return campaign

    def _create_campaign(self, payload: dict) -> dict:
        try:
            return self.client.create_campaign(payload)
        except KeitaroError as exc:
            if "alias" not in str(exc).lower():
                raise
            payload = {**payload, "alias": secrets.token_hex(3)}
            return self.client.create_campaign(payload)


def _find_domain(domains: list[dict], expected: str) -> dict:
    host = _host(expected)
    matches = [item for item in domains if _host(str(item.get("name") or "")) == host]
    if not matches:
        sample = ", ".join(str(item.get("name")) for item in domains[:8]) or "—"
        raise AppError(f"В Keitaro нет домена {expected}. Сейчас доступны: {sample}")
    return matches[0]


def _find_named(items: list[dict], expected: str, label: str) -> dict:
    want = expected.strip().lower()
    matches = [item for item in items if str(item.get("name") or "").strip().lower() == want]
    if not matches:
        sample = ", ".join(str(item.get("name")) for item in items[:8]) or "—"
        raise AppError(f"Не найден {label} «{expected}». В трекере есть: {sample}")
    return matches[0]

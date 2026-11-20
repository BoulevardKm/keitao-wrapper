from app.config import Settings
from app.errors import AppError
from app.keitaro import KeitaroError
from app.services.creator import CampaignCreator, parse_geos


class FakeKeitaro:
    def __init__(self, reject_empty_alias=False):
        self.reject_empty_alias = reject_empty_alias
        self.offers = {10: {"id": 10, "name": "Beauty RO", "state": "active"}}
        self.domains = [{"id": 3, "name": "in.posdk.xyz"}]
        self.groups = [{"id": 5, "name": "FORTESTS"}]
        self.sources = [{"id": 7, "name": "FORTESTS"}]
        self.created_campaigns = []
        self.created_streams = []
        self.deleted = []
        self.fail_streams = False
        self._next_campaign = 42
        self._next_stream = 100

    def get_offer(self, offer_id):
        offer = self.offers.get(offer_id)
        if offer is None:
            raise KeitaroError(404, "not found")
        return offer

    def list_domains(self):
        return self.domains

    def list_groups(self, group_type):
        assert group_type == "campaigns"
        return self.groups

    def list_traffic_sources(self):
        return self.sources

    def create_campaign(self, payload):
        self.created_campaigns.append(payload)
        if payload.get("alias") == "" and self.reject_empty_alias:
            raise KeitaroError(422, "alias must not be empty")
        campaign_id = self._next_campaign
        self._next_campaign += 1
        return {"id": campaign_id, "alias": payload.get("alias") or "wVqNTR", **payload}

    def delete_campaign(self, campaign_id):
        self.deleted.append(campaign_id)

    def create_stream(self, payload):
        if self.fail_streams:
            raise KeitaroError(400, "unknown filter country")
        self.created_streams.append(payload)
        stream_id = self._next_stream
        self._next_stream += 1
        return {"id": stream_id, **payload}


def settings():
    return Settings(
        keitaro_base_url="https://yellowplastercrutch.com",
        keitaro_api_key="test",
        keitaro_domain="https://in.posdk.xyz/",
        keitaro_group="fortests",
        keitaro_source="FORTESTS",
        keitaro_safe_url="https://google.com",
        database_url="sqlite://",
    )


def test_parse_geos_accepts_a_comma_separated_list_once():
    assert parse_geos(" mx, au; MX ") == ["MX", "AU"]


def test_parse_geos_rejects_a_country_name():
    try:
        parse_geos("Australia")
    except AppError as exc:
        assert "Australia" in str(exc)
    else:
        raise AssertionError("expected AppError")


def test_create_builds_position_campaign_and_two_streams():
    fake = FakeKeitaro()
    campaign = CampaignCreator(fake, settings()).create(" Spring ", "MX, AU", 10)

    assert campaign["id"] == 42
    payload = fake.created_campaigns[0]
    assert payload["name"] == "Spring"
    assert payload["type"] == "position"
    assert payload["cost_type"] == "CPC"
    assert payload["cost_value"] == 0
    assert payload["cost_currency"] == "USD"
    assert payload["cost_auto"] is True
    assert payload["domain_id"] == 3
    assert payload["group_id"] == 5
    assert payload["traffic_source_id"] == 7
    assert payload["parameters"]["cost"]["name"] == "cost"

    google, offers = fake.created_streams
    assert google["name"] == "Flow 1"
    assert google["position"] == 1
    assert google["schema"] == "redirect"
    assert google["action_type"] == "http"
    assert google["action_payload"] == "https://google.com"
    assert google["filters"] == [{"name": "country", "mode": "accept", "payload": ["MX", "AU"]}]
    assert offers["name"] == "Flow 2"
    assert offers["position"] == 2
    assert offers["schema"] == "landings"
    assert offers["offers"] == [{"offer_id": 10, "share": 100, "state": "active"}]
    assert google["campaign_id"] == offers["campaign_id"] == 42


def test_create_retries_when_keitaro_rejects_an_empty_alias():
    fake = FakeKeitaro(reject_empty_alias=True)
    CampaignCreator(fake, settings()).create("Retry", "AU", 10)
    assert fake.created_campaigns[0]["alias"] == ""
    assert fake.created_campaigns[1]["alias"]
    assert len(fake.created_streams) == 2


def test_failed_stream_rolls_the_campaign_back():
    fake = FakeKeitaro()
    fake.fail_streams = True
    try:
        CampaignCreator(fake, settings()).create("Broken", "AU", 10)
    except AppError as exc:
        assert "удалена" in str(exc)
    else:
        raise AssertionError("expected AppError")
    assert fake.deleted == [42]


def test_create_stops_before_any_request_when_the_domain_is_missing():
    fake = FakeKeitaro()
    fake.domains = [{"id": 1, "name": "other.com"}]
    try:
        CampaignCreator(fake, settings()).create("Nope", "AU", 10)
    except AppError as exc:
        assert "домена" in str(exc)
    else:
        raise AssertionError("expected AppError")
    assert fake.created_campaigns == []

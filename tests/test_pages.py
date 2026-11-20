from urllib.parse import unquote

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import CampaignRecord, OfferBinding, StreamRecord
from tests.test_editor import memory_session


def client_with(session):
    def override():
        yield session

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_home_and_invalid_geo(monkeypatch):
    session = memory_session()
    client = client_with(session)
    try:
        home = client.get("/")
        assert home.status_code == 200
        assert "Новая кампания" in home.text
        assert "MX, AU, RO" in home.text

        response = client.post(
            "/campaigns",
            data={"name": "Spring", "geo": "Australia", "offer_id": "10"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "Australia" in unquote(response.headers["location"])
    finally:
        app.dependency_overrides.clear()


def test_editor_page_shows_archive_actions_and_unpublished_state():
    session = memory_session()
    campaign = CampaignRecord(
        keitaro_id=5,
        name="campaign 2",
        alias="wVqNTR",
        domain_name="in.posdk.xyz",
        group_name="FORTESTS",
        source_name="FORTESTS",
    )
    plain = StreamRecord(keitaro_id=10, name="Flow 1", position=1, offer_stream=False, dirty=False, published_json="[]")
    offers = StreamRecord(keitaro_id=11, name="Flow 2", position=2, offer_stream=True, dirty=True, published_json="[]")
    offers.bindings.append(OfferBinding(offer_id=1, name="One", share=100, pinned=False, status="active", pending_add=False))
    offers.bindings.append(OfferBinding(offer_id=2, name="Two", share=0, pinned=False, status="removed", pending_add=False))
    campaign.streams.extend([plain, offers])
    session.add(campaign)
    session.commit()

    client = client_with(session)
    try:
        page = client.get("/campaigns/5")
        assert page.status_code == 200
        assert "не опубликовано" in page.text
        assert "Bring back" in page.text
        assert "Фильтры и адрес редиректа не показываем" in page.text
        assert "https://in.posdk.xyz/wVqNTR" in page.text
        assert "Push to Keitaro" in page.text
    finally:
        app.dependency_overrides.clear()

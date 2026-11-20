import copy

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.errors import AppError
from app.keitaro import KeitaroError
from app.models import CampaignRecord
from app.services.editor import StreamEditor


class FakeKeitaro:
    def __init__(self):
        self.offers = {
            1: {"id": 1, "name": "One", "state": "active"},
            2: {"id": 2, "name": "Two", "state": "active"},
            3: {"id": 3, "name": "Three", "state": "active"},
        }
        self.domains = [{"id": 3, "name": "in.posdk.xyz"}]
        self.groups = [{"id": 8, "name": "FORTESTS"}]
        self.sources = [{"id": 9, "name": "FORTESTS"}]
        self.campaigns = {
            5: {
                "id": 5,
                "name": "campaign 2",
                "alias": "wVqNTR",
                "state": "active",
                "domain_id": 3,
                "group_id": 8,
                "traffic_source_id": 9,
            }
        }
        self.streams = {
            5: [
                {"id": 10, "name": "Flow 1", "position": 1, "offers": []},
                {
                    "id": 11,
                    "name": "Flow 2",
                    "position": 2,
                    "offers": [
                        {"offer_id": 1, "share": 50, "state": "active"},
                        {"offer_id": 2, "share": 50, "state": "active"},
                    ],
                },
            ]
        }
        self.updated = []

    def get_campaign(self, campaign_id):
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            raise KeitaroError(404, "missing")
        return campaign

    def list_campaigns(self):
        return list(self.campaigns.values())

    def get_streams(self, campaign_id):
        return copy.deepcopy(self.streams.get(campaign_id, []))

    def list_offers(self):
        return list(self.offers.values())

    def get_offer(self, offer_id):
        offer = self.offers.get(offer_id)
        if offer is None:
            raise KeitaroError(404, "missing offer")
        return offer

    def list_domains(self):
        return self.domains

    def list_groups(self, group_type):
        return self.groups

    def list_traffic_sources(self):
        return self.sources

    def update_stream(self, stream_id, payload):
        self.updated.append((stream_id, copy.deepcopy(payload)))
        for streams in self.streams.values():
            for stream in streams:
                if stream["id"] == stream_id and "offers" in payload:
                    stream["offers"] = payload["offers"]
        return payload


def memory_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def shares(stream):
    return {binding.offer_id: (binding.share, binding.status, binding.pinned) for binding in stream.bindings}


def test_fetch_separates_plain_streams_from_offer_streams():
    editor = StreamEditor(FakeKeitaro(), memory_session())
    campaign = editor.fetch("wVqNTR")
    assert campaign.keitaro_id == 5
    assert campaign.alias == "wVqNTR"
    assert campaign.domain_name == "in.posdk.xyz"
    plain, offers = sorted(campaign.streams, key=lambda stream: stream.position)
    assert plain.offer_stream is False
    assert plain.bindings == []
    assert offers.offer_stream is True
    assert shares(offers) == {1: (50, "active", False), 2: (50, "active", False)}
    assert offers.dirty is False


def test_add_cancel_and_push_roundtrip():
    fake = FakeKeitaro()
    db = memory_session()
    editor = StreamEditor(fake, db)
    campaign = editor.fetch("5")
    stream = next(item for item in campaign.streams if item.offer_stream)

    editor.add_offer(5, stream.id, 3)
    db.refresh(stream)
    assert stream.dirty is True
    assert shares(stream)[1][0] == 34
    assert shares(stream)[2][0] == 33
    assert shares(stream)[3] == (33, "active", False)
    assert sum(share for share, status, _ in shares(stream).values() if status == "active") == 100

    editor.cancel(5, stream.id)
    db.refresh(stream)
    assert stream.dirty is False
    assert shares(stream) == {1: (50, "active", False), 2: (50, "active", False)}

    editor.add_offer(5, stream.id, 3)
    editor.push(5, stream.id)
    db.refresh(stream)
    assert stream.dirty is False
    sent_id, payload = fake.updated[-1]
    assert sent_id == 11
    assert sorted(payload["offers"], key=lambda offer: offer["offer_id"]) == [
        {"offer_id": 1, "share": 34, "state": "active"},
        {"offer_id": 2, "share": 33, "state": "active"},
        {"offer_id": 3, "share": 33, "state": "active"},
    ]
    assert all(binding.pending_add is False for binding in stream.bindings)


def test_remove_archives_the_offer_until_it_is_published_or_brought_back():
    fake = FakeKeitaro()
    db = memory_session()
    editor = StreamEditor(fake, db)
    stream = next(item for item in editor.fetch("5").streams if item.offer_stream)
    first = next(binding for binding in stream.bindings if binding.offer_id == 1)

    editor.remove_offer(5, stream.id, first.id)
    db.refresh(stream)
    assert shares(stream)[1] == (0, "removed", False)
    assert shares(stream)[2] == (100, "active", False)
    assert stream.dirty is True

    editor.push(5, stream.id)
    assert fake.updated[-1][1]["offers"] == [{"offer_id": 2, "share": 100, "state": "active"}]
    removed = next(binding for binding in stream.bindings if binding.offer_id == 1)
    editor.restore_offer(5, stream.id, removed.id)
    db.refresh(stream)
    assert stream.dirty is True
    assert shares(stream)[1][1] == "active"
    assert sum(share for share, status, _ in shares(stream).values() if status == "active") == 100


def test_pin_is_kept_when_another_offer_is_added():
    fake = FakeKeitaro()
    db = memory_session()
    editor = StreamEditor(fake, db)
    stream = next(item for item in editor.fetch("5").streams if item.offer_stream)
    first = next(binding for binding in stream.bindings if binding.offer_id == 1)
    editor.set_pin(5, stream.id, first.id, True)
    db.refresh(stream)
    assert stream.dirty is False

    editor.add_offer(5, stream.id, 3)
    db.refresh(stream)
    assert shares(stream)[1] == (50, "active", True)
    assert shares(stream)[2][0] == 25
    assert shares(stream)[3][0] == 25


def test_fetch_after_external_delete_archives_the_offer():
    fake = FakeKeitaro()
    db = memory_session()
    editor = StreamEditor(fake, db)
    editor.fetch("5")
    fake.streams[5][1]["offers"] = [{"offer_id": 2, "share": 100, "state": "active"}]
    campaign = editor.fetch("5")
    stream = next(item for item in campaign.streams if item.offer_stream)
    assert shares(stream)[1] == (0, "removed", False)
    assert shares(stream)[2] == (100, "active", False)
    assert stream.dirty is False


def test_unknown_offer_is_rejected():
    editor = StreamEditor(FakeKeitaro(), memory_session())
    stream = next(item for item in editor.fetch("5").streams if item.offer_stream)
    try:
        editor.add_offer(5, stream.id, 404)
    except KeitaroError:
        pass
    else:
        raise AssertionError("expected KeitaroError")


def test_plain_stream_rejects_offer_edits():
    editor = StreamEditor(FakeKeitaro(), memory_session())
    plain = next(item for item in editor.fetch("5").streams if not item.offer_stream)
    try:
        editor.add_offer(5, plain.id, 1)
    except AppError as exc:
        assert "нет офферов" in str(exc)
    else:
        raise AssertionError("expected AppError")


def test_campaign_row_roundtrip_type():
    db = memory_session()
    db.add(CampaignRecord(keitaro_id=1, name="x"))
    db.commit()
    assert db.query(CampaignRecord).one().name == "x"

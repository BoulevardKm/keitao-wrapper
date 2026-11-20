"""Local editor for offers inside an existing Keitaro campaign.

Keitaro is updated only by push. Fetch re-reads the tracker: offers that
vanished there stay in the local archive, and unpublished additions are dropped.
Streams without offers are stored as rows and their filters are not parsed.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import AppError
from app.keitaro import KeitaroClient, KeitaroError
from app.models import CampaignRecord, OfferBinding, StreamRecord
from app.services.shares import ShareItem, distribute, dump_items, items_from_bindings, load_items, merge_remote


class StreamEditor:
    def __init__(self, client: KeitaroClient, db: Session):
        self.client = client
        self.db = db

    def list_campaigns(self) -> list[CampaignRecord]:
        return list(self.db.scalars(select(CampaignRecord).order_by(CampaignRecord.id.desc())))

    def get_campaign(self, keitaro_id: int) -> CampaignRecord | None:
        statement = (
            select(CampaignRecord)
            .options(selectinload(CampaignRecord.streams).selectinload(StreamRecord.bindings))
            .where(CampaignRecord.keitaro_id == keitaro_id)
        )
        return self.db.scalars(statement).one_or_none()

    def fetch(self, raw: str) -> CampaignRecord:
        campaign = self._resolve_campaign(raw)
        keitaro_id = int(campaign["id"])
        try:
            remote_streams = self.client.get_streams(keitaro_id)
            offer_names = self._offer_names()
        except KeitaroError:
            self.db.rollback()
            raise

        record = self.get_campaign(keitaro_id)
        if record is None:
            record = CampaignRecord(keitaro_id=keitaro_id, name=campaign.get("name") or f"Campaign {keitaro_id}")
            self.db.add(record)
        record.name = campaign.get("name") or record.name
        record.alias = campaign.get("alias")
        record.domain_name = self._lookup_name(self.client.list_domains(), campaign.get("domain_id")) or record.domain_name
        record.group_name = self._lookup_name(
            self.client.list_groups("campaigns"), campaign.get("group_id")
        ) or record.group_name
        record.source_name = self._lookup_name(
            self.client.list_traffic_sources(), campaign.get("traffic_source_id")
        ) or record.source_name

        seen: set[int] = set()
        for remote in remote_streams:
            remote_id = int(remote["id"])
            seen.add(remote_id)
            stream = next((item for item in record.streams if item.keitaro_id == remote_id), None)
            if stream is None:
                stream = StreamRecord(
                    keitaro_id=remote_id,
                    name=remote.get("name") or f"Flow {remote_id}",
                    position=int(remote.get("position") or 0),
                    offer_stream=False,
                    dirty=False,
                    published_json="[]",
                )
                record.streams.append(stream)
            stream.name = remote.get("name") or stream.name
            stream.position = int(remote.get("position") or 0)
            remote_offers = _remote_shares(remote)
            if remote_offers or stream.offer_stream:
                stream.offer_stream = True
                merged = merge_remote(items_from_bindings(stream.bindings), remote_offers, offer_names)
                self._write_bindings(stream, merged)
                stream.published_json = dump_items(merged)
            else:
                stream.offer_stream = False
                self._write_bindings(stream, [])
                stream.published_json = "[]"
            stream.dirty = False

        for stream in list(record.streams):
            if stream.keitaro_id not in seen:
                record.streams.remove(stream)

        self.db.commit()
        self.db.refresh(record)
        return record

    def add_offer(self, keitaro_campaign_id: int, stream_id: int, offer_id: int) -> None:
        self._mutate(keitaro_campaign_id, stream_id, lambda stream: self._add(stream, offer_id))

    def remove_offer(self, keitaro_campaign_id: int, stream_id: int, binding_id: int) -> None:
        self._mutate(keitaro_campaign_id, stream_id, lambda stream: self._remove(stream, binding_id))

    def restore_offer(self, keitaro_campaign_id: int, stream_id: int, binding_id: int) -> None:
        binding = self._binding(keitaro_campaign_id, stream_id, binding_id)
        self.add_offer(keitaro_campaign_id, stream_id, binding.offer_id)

    def set_pin(self, keitaro_campaign_id: int, stream_id: int, binding_id: int, pinned: bool) -> None:
        try:
            stream = self._stream(keitaro_campaign_id, stream_id)
            binding = self._binding_on(stream, binding_id)
            if binding.status != "active":
                raise AppError("Нельзя запинить долю оффера из архива.")
            binding.pinned = pinned
            snapshot = load_items(stream.published_json)
            for item in snapshot:
                if item.offer_id == binding.offer_id:
                    item.pinned = pinned
            if any(item.offer_id == binding.offer_id for item in snapshot):
                stream.published_json = dump_items(snapshot)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def push(self, keitaro_campaign_id: int, stream_id: int) -> None:
        stream = self._stream(keitaro_campaign_id, stream_id)
        if not stream.offer_stream:
            raise AppError("У этого потока нет офферов.")
        items = items_from_bindings(stream.bindings)
        active = [item for item in items if item.status == "active"]
        if active and sum(item.share for item in active) != 100:
            raise AppError("Сумма долей активных офферов не равна 100%.")
        payload = {
            "offers": [
                {"offer_id": item.offer_id, "share": int(item.share), "state": "active"}
                for item in active
            ]
        }
        try:
            self.client.update_stream(stream.keitaro_id, payload)
        except KeitaroError:
            self.db.rollback()
            raise
        for item in items:
            if item.status == "active":
                item.pending_add = False
        self._write_bindings(stream, items)
        stream.dirty = False
        stream.published_json = dump_items(items)
        self.db.commit()

    def cancel(self, keitaro_campaign_id: int, stream_id: int) -> None:
        try:
            stream = self._stream(keitaro_campaign_id, stream_id)
            if not stream.dirty:
                return
            self._write_bindings(stream, load_items(stream.published_json))
            stream.dirty = False
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _add(self, stream: StreamRecord, offer_id: int) -> None:
        if offer_id <= 0:
            raise AppError("Укажите оффер.")
        offer = self.client.get_offer(offer_id)
        if offer.get("state") == "deleted":
            raise AppError(f"Оффер {offer_id} удалён в Keitaro.")
        items = items_from_bindings(stream.bindings)
        current = next((item for item in items if item.offer_id == offer_id), None)
        if current and current.status == "active":
            raise AppError(f"Оффер {offer_id} уже есть в этом потоке.")
        name = offer.get("name") or f"Offer {offer_id}"
        if current:
            current.status = "active"
            current.pinned = False
            current.share = 0
            current.name = name
        else:
            items.append(
                ShareItem(
                    offer_id=offer_id,
                    name=name,
                    share=0,
                    pinned=False,
                    status="active",
                    pending_add=True,
                )
            )
        distribute(items)
        self._write_bindings(stream, items)
        stream.dirty = True

    def _remove(self, stream: StreamRecord, binding_id: int) -> None:
        binding = self._binding_on(stream, binding_id)
        if binding.status != "active":
            raise AppError("Этот оффер уже в архиве.")
        items = items_from_bindings(stream.bindings)
        target = next(item for item in items if item.offer_id == binding.offer_id)
        target.status = "removed"
        target.share = 0
        target.pinned = False
        distribute(items)
        self._write_bindings(stream, items)
        stream.dirty = True

    def _mutate(self, keitaro_campaign_id: int, stream_id: int, action) -> None:
        try:
            stream = self._stream(keitaro_campaign_id, stream_id)
            if not stream.offer_stream:
                raise AppError("У этого потока нет офферов, его содержимое не редактируется.")
            action(stream)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _resolve_campaign(self, raw: str) -> dict:
        text = raw.strip()
        if not text:
            raise AppError("Укажите id или alias кампании.")
        try:
            if text.isdigit():
                return self.client.get_campaign(int(text))
            for campaign in self.client.list_campaigns():
                if campaign.get("state") == "deleted":
                    continue
                if str(campaign.get("alias") or "") == text:
                    return campaign
        except KeitaroError as exc:
            if exc.status == 404:
                raise AppError(f"Кампания «{text}» не найдена в Keitaro.") from exc
            raise
        raise AppError(f"Кампания «{text}» не найдена в Keitaro.")

    def _offer_names(self) -> dict[int, str]:
        names: dict[int, str] = {}
        for offer in self.client.list_offers():
            if offer.get("id") is None:
                continue
            names[int(offer["id"])] = offer.get("name") or f"Offer {offer['id']}"
        return names

    def _stream(self, keitaro_campaign_id: int, stream_id: int) -> StreamRecord:
        stream = self.db.get(StreamRecord, stream_id)
        if stream is None or stream.campaign.keitaro_id != keitaro_campaign_id:
            raise AppError("Поток не найден в этой кампании.")
        return stream

    def _binding(self, keitaro_campaign_id: int, stream_id: int, binding_id: int) -> OfferBinding:
        stream = self._stream(keitaro_campaign_id, stream_id)
        return self._binding_on(stream, binding_id)

    @staticmethod
    def _binding_on(stream: StreamRecord, binding_id: int) -> OfferBinding:
        binding = next((item for item in stream.bindings if item.id == binding_id), None)
        if binding is None:
            raise AppError("Оффер не найден в этом потоке.")
        return binding

    @staticmethod
    def _write_bindings(stream: StreamRecord, items: list[ShareItem]) -> None:
        by_offer = {binding.offer_id: binding for binding in list(stream.bindings)}
        seen: set[int] = set()
        for item in items:
            seen.add(item.offer_id)
            binding = by_offer.get(item.offer_id)
            if binding is None:
                binding = OfferBinding(offer_id=item.offer_id, name=item.name)
                stream.bindings.append(binding)
            binding.name = item.name
            binding.share = int(item.share)
            binding.pinned = bool(item.pinned)
            binding.status = item.status
            binding.pending_add = bool(item.pending_add)
        for offer_id, binding in by_offer.items():
            if offer_id not in seen:
                stream.bindings.remove(binding)

    @staticmethod
    def _lookup_name(items: list[dict], item_id) -> str | None:
        if item_id in (None, "", 0):
            return None
        for item in items:
            if item.get("id") == item_id or str(item.get("id")) == str(item_id):
                return item.get("name")
        return None


def _remote_shares(stream: dict) -> dict[int, int]:
    shares: dict[int, int] = {}
    for entry in stream.get("offers") or []:
        if entry.get("state") == "disabled":
            continue
        if entry.get("offer_id") is None:
            continue
        shares[int(entry["offer_id"])] = int(entry.get("share") or 0)
    return shares

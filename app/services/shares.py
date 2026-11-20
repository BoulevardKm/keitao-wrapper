"""Offer shares and the sync between a local stream and Keitaro.

Shares are integers and the active ones sum to 100. A pinned share stays put.
The leftover percent is split across the other active offers; the remainder of
that division goes to the offers with the smaller Keitaro id, so 100 / 3 is
34, 33, 33 rather than three 33s.
"""

import json
from dataclasses import dataclass

from app.errors import AppError


@dataclass
class ShareItem:
    offer_id: int
    name: str
    share: int
    pinned: bool
    status: str
    pending_add: bool = False


def distribute(items: list) -> None:
    for item in items:
        if item.status != "active":
            item.share = 0
            item.pinned = False

    active = [item for item in items if item.status == "active"]
    if len(active) == 1:
        active[0].share = 100
        return

    pinned = [item for item in active if item.pinned]
    free = sorted((item for item in active if not item.pinned), key=lambda item: item.offer_id)
    pinned_sum = sum(int(item.share) for item in pinned)

    if pinned_sum > 100:
        raise AppError(f"Сумма запиненных долей {pinned_sum}% — это больше 100%")
    if not free:
        if active and pinned_sum != 100:
            raise AppError(
                f"Все оставшиеся доли запинены и в сумме дают {pinned_sum}%. Снимите пин, чтобы пересчитать поток."
            )
        return
    if pinned_sum == 100:
        raise AppError("Запиненные доли уже занимают 100%. Снимите пин, чтобы изменить состав потока.")

    remainder = 100 - pinned_sum
    base, extra = divmod(remainder, len(free))
    for index, item in enumerate(free):
        item.share = base + (1 if index < extra else 0)

    total = sum(int(item.share) for item in active)
    if total != 100:
        raise AppError(f"Сумма долей получилась {total}%, а не 100%")


def merge_remote(local: list, remote_shares: dict[int, int], names: dict[int, str]) -> list[ShareItem]:
    """Rebuild a stream from Keitaro.

    An offer that disappeared from the tracker stays in the archive. An offer
    that was only added locally and never published is dropped. Shares are
    taken from Keitaro as they are, without redistribution.
    """

    merged: list[ShareItem] = []
    seen: set[int] = set()
    for item in local:
        seen.add(item.offer_id)
        if item.offer_id in remote_shares:
            merged.append(
                ShareItem(
                    offer_id=item.offer_id,
                    name=names.get(item.offer_id, item.name),
                    share=int(remote_shares[item.offer_id]),
                    pinned=bool(item.pinned),
                    status="active",
                    pending_add=False,
                )
            )
        elif item.pending_add:
            continue
        else:
            merged.append(
                ShareItem(
                    offer_id=item.offer_id,
                    name=item.name,
                    share=0,
                    pinned=False,
                    status="removed",
                    pending_add=False,
                )
            )
    for offer_id, share in sorted(remote_shares.items()):
        if offer_id in seen:
            continue
        merged.append(
            ShareItem(
                offer_id=offer_id,
                name=names.get(offer_id, f"Offer {offer_id}"),
                share=int(share),
                pinned=False,
                status="active",
                pending_add=False,
            )
        )
    return merged


def dump_items(items: list) -> str:
    payload = [
        {
            "offer_id": item.offer_id,
            "name": item.name,
            "share": int(item.share),
            "pinned": bool(item.pinned),
            "status": item.status,
            "pending_add": False,
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False)


def load_items(raw: str | None) -> list[ShareItem]:
    if not raw:
        return []
    data = json.loads(raw)
    return [
        ShareItem(
            offer_id=int(item["offer_id"]),
            name=item.get("name") or f"Offer {item['offer_id']}",
            share=int(item.get("share") or 0),
            pinned=bool(item.get("pinned")),
            status=item.get("status") or "active",
            pending_add=False,
        )
        for item in data
    ]


def items_from_bindings(bindings: list) -> list[ShareItem]:
    ordered = sorted(bindings, key=lambda binding: binding.id or 0)
    return [
        ShareItem(
            offer_id=binding.offer_id,
            name=binding.name,
            share=binding.share,
            pinned=binding.pinned,
            status=binding.status,
            pending_add=binding.pending_add,
        )
        for binding in ordered
    ]


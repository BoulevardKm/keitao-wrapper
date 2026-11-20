from app.errors import AppError
from app.services.shares import ShareItem, distribute, merge_remote


def item(offer_id, share=0, pinned=False, status="active", pending_add=False, name=""):
    return ShareItem(
        offer_id=offer_id,
        name=name or f"Offer {offer_id}",
        share=share,
        pinned=pinned,
        status=status,
        pending_add=pending_add,
    )


def test_one_offer_takes_everything():
    offers = [item(1)]
    distribute(offers)
    assert offers[0].share == 100


def test_three_offers_sum_to_100_and_remainder_goes_to_smaller_id():
    offers = [item(3), item(1), item(2)]
    distribute(offers)
    by_id = {offer.offer_id: offer.share for offer in offers}
    assert by_id == {1: 34, 2: 33, 3: 33}
    assert sum(by_id.values()) == 100


def test_four_offers_are_even():
    offers = [item(index) for index in range(1, 5)]
    distribute(offers)
    assert [offer.share for offer in offers] == [25, 25, 25, 25]


def test_pinned_share_stays_while_the_rest_splits_the_leftover():
    pinned = item(1, share=25, pinned=True)
    offers = [pinned, item(2), item(3)]
    distribute(offers)
    assert pinned.share == 25
    assert {offer.offer_id: offer.share for offer in offers} == {1: 25, 2: 38, 3: 37}


def test_removed_offer_is_excluded_and_loses_its_pin():
    offers = [item(1, share=40, pinned=True), item(2, status="removed", share=99, pinned=True)]
    distribute(offers)
    assert offers[0].share == 100
    assert offers[1].share == 0
    assert offers[1].pinned is False


def test_all_pinned_shares_that_already_sum_to_100_are_left_alone():
    offers = [item(1, share=25, pinned=True), item(2, share=75, pinned=True)]
    distribute(offers)
    assert [offer.share for offer in offers] == [25, 75]


def test_cannot_recalculate_when_pins_already_occupy_100_percent():
    offers = [item(1, share=100, pinned=True), item(2)]
    try:
        distribute(offers)
    except AppError as exc:
        assert "100%" in str(exc)
    else:
        raise AssertionError("expected AppError")


def test_fetch_archives_missing_offers_and_drops_unpublished_ones():
    local = [item(1, share=50), item(2, share=50), item(9, pending_add=True)]
    merged = merge_remote(local, {1: 40, 3: 60}, {1: "One", 3: "Three"})
    by_id = {offer.offer_id: offer for offer in merged}
    assert by_id[1].share == 40 and by_id[1].status == "active"
    assert by_id[2].status == "removed" and by_id[2].share == 0
    assert by_id[3].status == "active" and by_id[3].name == "Three"
    assert 9 not in by_id


def test_fetch_keeps_a_pin_and_brings_back_an_offer_that_returned():
    local = [item(1, share=25, pinned=True), item(2, status="removed")]
    merged = merge_remote(local, {1: 70, 2: 30}, {1: "One", 2: "Two"})
    by_id = {offer.offer_id: offer for offer in merged}
    assert by_id[1].pinned is True and by_id[1].share == 70
    assert by_id[2].status == "active" and by_id[2].share == 30

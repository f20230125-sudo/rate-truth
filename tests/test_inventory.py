from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from rate_truth.supplier.inventory import SoldOut
from rate_truth.supplier.models import RoomType, dubai_today


def test_stock_is_seeded_and_never_negative(engine, hotel):
    start = dubai_today()
    for room in RoomType:
        for offset in range(365):
            stock = engine.inventory.availability(hotel, start + timedelta(days=offset), 1, room)
            assert 0 <= stock["available"] <= stock["nights"][0]["capacity"]
            assert stock == engine.inventory.availability(
                hotel, start + timedelta(days=offset), 1, room
            )


def test_atomic_concurrent_holds_and_expiry(engine, hotel, fixed_inventory):
    inventory, now = fixed_inventory
    day = dubai_today()
    quote = engine.quote(hotel, day, 2, 2)
    original = inventory.availability(hotel, day, 2)
    available = original["available"]

    def attempt(_):
        try:
            return inventory.hold(hotel, quote, confirm=True)
        except SoldOut:
            return None

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(attempt, range(available + 20)))
    holds = [h for h in results if h]
    assert len(holds) == available
    assert inventory.availability(hotel, day, 2)["available"] == 0
    for h in holds:
        assert h["expires_at"] - h["created_at"] == timedelta(minutes=15)
        assert h["mock_only"] and h["booked"] is False
        assert h["rate_id"] == quote["rate_id"] and h["computed_at"] == quote["computed_at"]
    now[0] += timedelta(minutes=15)
    assert inventory.availability(hotel, day, 2) == original


def test_hold_all_nights_or_none_and_room_stock_independence(engine, hotel, fixed_inventory):
    inventory, _ = fixed_inventory
    day = dubai_today()
    one_night = engine.quote(hotel, day, 1, 2)
    for _ in range(inventory.availability(hotel, day, 1)["available"]):
        inventory.hold(hotel, one_night, confirm=True)
    next_night = inventory.availability(hotel, day + timedelta(days=1), 1)
    deluxe = inventory.availability(hotel, day, 1, RoomType.DELUXE)
    with pytest.raises(SoldOut):
        inventory.hold(hotel, engine.quote(hotel, day, 2, 2), confirm=True)
    assert inventory.availability(hotel, day + timedelta(days=1), 1) == next_night
    assert inventory.availability(hotel, day, 1, RoomType.DELUXE) == deluxe


@pytest.mark.parametrize("confirm", [False, None, "true", 1])
def test_mock_hold_requires_boolean_confirmation(engine, hotel, confirm):
    quote = engine.quote(hotel, dubai_today(), 1, 2)
    before = engine.inventory.availability(hotel, dubai_today(), 1)
    with pytest.raises(ValueError):
        engine.inventory.hold(hotel, quote, confirm=confirm)
    assert engine.inventory.availability(hotel, dubai_today(), 1) == before

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

from rate_truth.supplier.models import Plan, RoomType, dubai_today, money
from rate_truth.supplier.rates import RateEngine, area_for, los_discount


def test_determinism_and_traceability(engine, hotel):
    day = dubai_today() + timedelta(days=1)
    a = engine.quote(hotel, day, 2, 2, Plan.REFUNDABLE_BREAKFAST)
    b = engine.quote(hotel, day, 2, 2, Plan.REFUNDABLE_BREAKFAST)
    assert a["computed_at"] and b["computed_at"]
    assert a.pop("computed_at") is not None
    b.pop("computed_at")
    assert a == b
    assert a["rate_id"].startswith("rt_")
    changed_seed = RateEngine(seed=99).quote(hotel, day, 2, 2, Plan.REFUNDABLE_BREAKFAST)
    assert a["rate_id"] != changed_seed["rate_id"]
    assert a["synthetic"] and "SYNTHETIC" in a["disclosure"]


@pytest.mark.parametrize("plan", list(Plan))
@pytest.mark.parametrize("nights", [1, 3, 7, 30])
def test_all_in_invariant_and_nightly_sum(engine, hotel, plan, nights):
    result = engine.quote(hotel, dubai_today(), nights, 2, plan)
    base = Decimal(result["base"])
    assert base == sum(Decimal(n["base"]) for n in result["nightly"])
    assert Decimal(result["total"]) == base + sum(
        Decimal(i["amount"]) for i in result["line_items"]
    )
    assert len(result["line_items"]) == 4 * nights
    assert all(i["rule_id"] for i in result["line_items"])


def test_los_discount_on_identical_nights(engine, hotel):
    start = dubai_today()
    singles = [engine.quote(hotel, start + timedelta(days=i), 1, 2) for i in range(7)]
    for nights, discount in ((2, Decimal(0)), (3, Decimal("0.05")), (7, Decimal("0.10"))):
        stay = engine.quote(hotel, start, nights, 2)
        assert all(Decimal(n["los_discount"]) == discount for n in stay["nightly"])
        assert sum(Decimal(n["base"]) for n in stay["nightly"]) <= sum(
            Decimal(s["base"]) for s in singles[:nights]
        )
        # Recover unrounded room from a duplicate calculation via the nightly audit value;
        # rounding a displayed pre-LOS room can differ by at most one fils.
        for night in stay["nightly"]:
            expected = money(Decimal(night["room_before_los"]) * (1 - discount))
            assert abs(expected - Decimal(night["base"])) <= Decimal("0.01")
    assert [los_discount(n) for n in (1, 2, 3, 6, 7, 30)] == [
        Decimal(0),
        Decimal(0),
        Decimal(".05"),
        Decimal(".05"),
        Decimal(".10"),
        Decimal(".10"),
    ]


def test_room_plans_breakfast_and_capacity(engine, hotel):
    start = dubai_today()
    basic = engine.quote(hotel, start, 1, 2)
    breakfast = engine.quote(hotel, start, 1, 2, Plan.REFUNDABLE_BREAKFAST)
    nonref = engine.quote(hotel, start, 1, 2, Plan.NON_REFUNDABLE)
    assert Decimal(breakfast["base"]) - Decimal(basic["base"]) == Decimal(90)
    assert Decimal(nonref["base"]) < Decimal(basic["base"])
    assert len({basic["rate_id"], breakfast["rate_id"], nonref["rate_id"]}) == 3
    family = engine.quote(hotel, start, 1, 8, room_type=RoomType.FAMILY)
    assert family["bedrooms"] == 1 and family["room_type"] == "family"
    assert engine.room_types()[0]["capacity"] == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"nights": 0},
        {"nights": 31},
        {"guests": 0},
        {"guests": 9},
        {"guests": 3, "room_type": "standard"},
        {"plan": "made_up"},
        {"room_type": "made_up"},
        {"checkin": date(2000, 1, 1)},
        {"checkin": date(2027, 11, 12)},
    ],
)
def test_invalid_quote_inputs(engine, hotel, overrides):
    params = {"hotel": hotel, "checkin": dubai_today(), "nights": 1, "guests": 2, **overrides}
    with pytest.raises(ValueError):
        engine.quote(**params)


def test_unknown_stars_are_disclosed(engine, hotel):
    unknown = hotel.model_copy(update={"stars": None, "stars_tag": None, "stars_estimated": 3})
    result = engine.quote(unknown, dubai_today(), 1, 2)
    assert result["stars_used"] == 3 and result["stars_basis"] == "estimate"
    assert "estimated star" in " ".join(result["warnings"])
    assert result["line_items"][3]["amount"] == "10.00"


def test_season_weekend_area_and_occupancy_factors(engine, hotel):
    start = dubai_today()
    results = [engine.quote(hotel, start + timedelta(days=i), 1, 2) for i in range(365)]
    for quote in results:
        n = quote["nightly"][0]
        day = date.fromisoformat(n["date"])
        expected = (
            "1.12"
            if day.month in {11, 12, 1, 2, 3}
            else "0.88"
            if day.month in {6, 7, 8, 9}
            else "1"
        )
        assert n["season_factor"] == expected
        assert n["weekend_factor"] == ("1.06" if day.weekday() in {4, 5} else "1")
        assert Decimal("0.96") <= Decimal(n["yield_factor"]) <= Decimal("1.04")
    assert len({q["nightly"][0]["occupancy"] for q in results}) > 1
    assert area_for(hotel)[1] == Decimal("1.03")
    north = hotel.model_copy(update={"lat": 25.3})
    assert area_for(north)[1] == Decimal("0.97")


def test_rate_id_deterministic_across_processes(hotel):
    source = (
        "import json; from rate_truth.supplier.models import Hotel, dubai_today; "
        "from rate_truth.supplier.rates import RateEngine; "
        f"h=Hotel.model_validate_json({hotel.model_dump_json()!r}); "
        "from datetime import date; "
        "print(json.dumps(RateEngine(seed=2026).quote("
        "h,date(2026,11,11),1,2,as_of=date(2026,11,11))['rate_id']))"
    )
    ids = []
    for hashseed in ("1", "777"):
        process = subprocess.run(
            [sys.executable, "-c", source],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": hashseed},
        )
        ids.append(json.loads(process.stdout))
    assert ids[0] == ids[1]

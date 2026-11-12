"""Independent arithmetic and regressions for the M0/M1 review."""

import hashlib
from datetime import date, timedelta
from decimal import Decimal

import pytest

from rate_truth.settings import ROOT
from rate_truth.supplier.inventory import HoldLimit
from rate_truth.supplier.models import Hotel, dubai_today, money
from rate_truth.supplier.taxes import OutOfModelPeriod, TaxRules
from scripts.document_model import parameter_table


def test_document_parameters_match_code():
    assert parameter_table() in (ROOT / "docs/supplier-model.md").read_text(encoding="utf-8")


def test_full_public_stay_horizon(engine, hotel):
    final_night = dubai_today() + timedelta(days=365 + 29)
    assert TaxRules().at(final_night)
    assert engine.quote(hotel, dubai_today() + timedelta(days=365), 30, 2)["nights"] == 30
    with pytest.raises(OutOfModelPeriod):
        TaxRules().at(date(2029, 1, 1))


def test_estimated_stars_and_website(hotel):
    data = {**hotel.model_dump(), "stars": None, "stars_estimated": 4}
    assert Hotel(**data).pricing_stars == 4
    assert Hotel(**{**data, "website": "www.hometohome.ae"}).website.startswith("https://")
    for website in ("javascript:alert(1)", "file:///tmp/a", "https:///no-host"):
        assert Hotel(**{**data, "website": website}).website is None


def independent_room(hotel, night):
    def hashed(*parts):
        return int.from_bytes(
            hashlib.sha256("|".join(map(str, (2026, *parts))).encode()).digest()[:8], "big"
        )

    capacity = 12 + hashed(hotel.id, "standard", "capacity") % 29
    demand = 65 if night.month in {11, 12, 1, 2, 3} else 40
    demand += hashed(hotel.id, "standard", night, "demand") % 26
    occupancy = Decimal(capacity * demand // 100) / capacity
    season = (
        Decimal("1.12")
        if night.month in {11, 12, 1, 2, 3}
        else (Decimal("0.88") if night.month in {6, 7, 8, 9} else Decimal(1))
    )
    return (
        Decimal(620)
        * Decimal("1.03")
        * (Decimal(95 + hashed(hotel.id, "price") % 11) / 100)
        * season
        * (Decimal("1.06") if night.weekday() in {4, 5} else 1)
        * (Decimal("0.96") + Decimal("0.08") * occupancy)
    )


@pytest.mark.parametrize("nights,discount", [(1, "0"), (3, ".05"), (7, ".10")])
@pytest.mark.parametrize("plan,factor", [("refundable", "1"), ("non_refundable", ".90")])
def test_independent_base_and_exact_discounts(engine, hotel, nights, discount, plan, factor):
    day = dubai_today()
    expected = sum(
        money(
            independent_room(hotel, day + timedelta(days=i))
            * Decimal(factor)
            * (1 - Decimal(discount))
        )
        for i in range(nights)
    )
    assert Decimal(engine.quote(hotel, day, nights, 2, plan)["base"]) == expected


def test_engine_relief_boundary_and_td_cap(engine, hotel):
    q = engine.quote(hotel, date(2026, 3, 31), 2, 2, as_of=date(2026, 3, 31))
    td = [i for i in q["line_items"] if i["name"] == "tourism_dirham"]
    assert [i["remittance_status"] for i in td] == ["normal", "remittance_exempt"]
    assert [i["amount"] for i in td] == ["20.00", "20.00"]
    rules = engine.taxes
    assert rules.for_night(Decimal(100), dubai_today(), 5, rooms=3)[3].amount == 60
    assert rules.for_night(Decimal(100), dubai_today(), 5, consecutive_night=31)[3].amount == 0
    # Shorten the configured cap: prove the engine reads it for the stay, not just the helper.
    next(r for r in rules.data["rules"] if r["kind"] == "tourism_dirham")[
        "max_consecutive_nights"
    ] = 1
    q = engine.quote(hotel, dubai_today(), 2, 2)
    assert [i["amount"] for i in q["line_items"] if i["name"] == "tourism_dirham"] == [
        "20.00",
        "0.00",
    ]


def test_hold_throttle_and_client_isolation(engine, hotel):
    for _ in range(60):
        engine.inventory.throttle("abusive")
    with pytest.raises(HoldLimit):
        engine.inventory.throttle("abusive")
    engine.inventory.throttle("other")
    engine.inventory._by_client["abusive"] = 32
    q = engine.quote(hotel, dubai_today(), 1, 2)
    with pytest.raises(HoldLimit, match="limit"):
        engine.inventory.hold(hotel, q, confirm=True, client_id="abusive")
    assert engine.inventory.hold(hotel, q, confirm=True, client_id="other")


def test_production_docs_disabled_and_total(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/hotels?limit=1").json()["total"] == 1


def test_model_period_error_code_at_http_boundary(client, engine, hotel):
    engine.taxes.data["model_period"]["effective_to"] = "2026-11-15"
    response = client.get("/quote", params={"hotel_id": hotel.id, "checkin": "2026-11-18"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "out_of_model_period"

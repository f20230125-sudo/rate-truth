import json
from datetime import date
from decimal import Decimal
from statistics import median

import pytest

from rate_truth.contract import folio
from rate_truth.geo import UNKNOWN_STARS, dedupe_pois, distance, enrich_hotels
from rate_truth.settings import DATA
from rate_truth.supplier.rates import RateEngine


@pytest.mark.parametrize("day", ["2026-12-14", "2027-04-14", "2027-08-11"])
def test_all_snapshot_folios_balance(day):
    engine = RateEngine(market_calibration={})
    assert len(engine.catalog.hotels) == 737
    for hotel in engine.catalog.hotels.values():
        result = folio(engine.quote(hotel, date.fromisoformat(day), 3, 2), hotel)
        assert sum(Decimal(i["amount"]) for i in result["lines"]) == Decimal(result["total"])
        assert len([i for i in result["lines"] if i["kind"] == "base"]) == 3
        assert all(i["rule_id"] and i["source_url"] and i["confidence"] for i in result["lines"])
        assert result["computed_at"].endswith("+04:00")
        assert set(result) == {
            "rate_id",
            "computed_at",
            "hotel_id",
            "hotel_name",
            "checkin",
            "nights",
            "guests",
            "room",
            "plan",
            "refundable",
            "breakfast",
            "lines",
            "total",
            "currency",
            "tax_rules_as_of",
            "synthetic",
        }
        if hotel.stars is None:
            assert UNKNOWN_STARS in result["lines"][0]["basis"]


def test_class_medians_calibrated_to_det():
    calibration = json.loads((DATA / "calibration.json").read_text())["calibration"]
    engine = RateEngine(market_calibration={})
    target = Decimal(calibration["adr_aed"])
    tolerance = Decimal(calibration["tolerance"])
    # The real snapshot contains no tagged one-star hotels; do not fabricate any.
    assert {h.pricing_stars for h in engine.catalog.hotels.values()} == {2, 3, 4, 5}
    for stars in (2, 3, 4, 5):
        hotels = [h for h in engine.catalog.hotels.values() if h.pricing_stars == stars]
        assert hotels
        for day in calibration["dates"]:
            midpoint = median(
                Decimal(engine.quote(h, date.fromisoformat(day), 1, 2)["base"]) for h in hotels
            )
            assert target * (1 - tolerance) <= midpoint <= target * (1 + tolerance)
    # Fixed winter/summer weekdays AND weekends; check every real property.
    for hotel in engine.catalog.hotels.values():
        bases = [
            Decimal(engine.quote(hotel, date.fromisoformat(d), 1, 2)["base"])
            for d in ("2026-12-14", "2026-12-18", "2027-08-11", "2027-08-13")
        ]
        assert max(bases) / min(bases) <= Decimal(calibration["max_peak_to_trough"])


def test_dedupe_name_type_radius_and_canonical_node():
    def poi(identifier, name, lat=25.2, kind="metro"):
        return {
            "id": identifier,
            "osm_type": identifier.split("/")[0],
            "name": name,
            "name_en": None,
            "lat": lat,
            "lon": 55.3,
            "types": [kind],
        }

    records = [
        poi("way/1", "Bur Juman"),
        poi("node/1", "BurJuman"),
        poi("node/2", "bur juman", 25.21),
        poi("node/3", "BurJuman", kind="beach"),
        poi("way/4", ""),
    ]
    result = dedupe_pois(records)
    assert len(result) == 4
    assert next(p for p in result if p["id"] == "node/1")["merged_osm_ids"] == ["node/1", "way/1"]
    assert dedupe_pois(result) == result


def test_areas_only_use_selected_nearby_landmarks():
    hotels = json.loads((DATA / "osm/hotels.json").read_text(encoding="utf-8"))["hotels"]
    pois = json.loads((DATA / "osm/pois.json").read_text(encoding="utf-8"))["pois"]
    assert enrich_hotels(hotels, pois) == hotels
    assert any(h["area"] is None for h in hotels)
    for hotel in hotels:
        if hotel["area"]:
            p = next(p for p in pois if hotel["area_source"].endswith(p["id"]))
            assert distance(hotel, p) <= 2000

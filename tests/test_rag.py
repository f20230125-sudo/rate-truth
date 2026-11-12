import json
from datetime import date

import pytest

from rate_truth.accuracy.sampler import audit
from rate_truth.rag.cards import Cards
from rate_truth.rag.retrieve import Retriever
from rate_truth.settings import ROOT
from rate_truth.supplier.catalog import Catalog
from rate_truth.supplier.rates import RateEngine


def test_nearest_name_type_dedupe_named_beach_and_proximity(engine, hotel):
    cards = Cards(engine.catalog)
    cards.__dict__["pois"] = [
        {
            "id": "node/1",
            "name": "Burj Khalifa",
            "types": ["burj_khalifa"],
            "lat": 25.2,
            "lon": 55.29,
        },
        {
            "id": "node/2",
            "name": "Burj Khalifa",
            "types": ["burj_khalifa"],
            "lat": 25.2,
            "lon": 55.30,
        },
        {"id": "way/3", "name": "", "types": ["beach"], "lat": 25.2, "lon": 55.28},
        {"id": "way/4", "name": "Named beach", "types": ["beach"], "lat": 25.2, "lon": 55.40},
    ]
    h = hotel.model_copy(
        update={"area": "Downtown Dubai", "area_source": "https://www.openstreetmap.org/node/1"}
    )
    record = cards.build(h)
    assert record["hotel"]["area"] == "near Downtown Dubai"
    assert len(record["hotel"]["landmarks"]) == 1
    assert record["hotel"]["nearest_beach"]["name"] == "Named beach"
    cards.__dict__["pois"] = cards.pois[:3]
    assert cards.build(h)["hotel"]["nearest_beach"]["name"] == "unnamed beach (OSM)"


def test_market_card_provenance(engine, hotel):
    cards = Cards(engine.catalog)
    cards.__dict__["observations"] = [
        {
            "hotel_id": hotel.id,
            "observation": {
                "provider": "Booking sites via TripAdvisor (Xotelo)",
                "fetched_at": "2026-11-11T00:00:00+00:00",
                "checkin": "2026-12-14",
                "checkout": "2026-12-15",
                "amount_aed": "123.00",
                "tax_label": "taxes unknown",
                "link": None,
            },
        }
    ]
    text = " ".join(f["text"] for f in cards.build(hotel)["card"]["facts"])
    assert "Booking sites via TripAdvisor (Xotelo)" in text
    assert "fetched_at 2026-11-11T00:00:00+00:00" in text
    assert "observed price, not a quote" in text


def test_retrieval_fallback_is_explicit(engine, tmp_path, monkeypatch):
    records = Cards(engine.catalog).records
    index = Retriever(records, directory=tmp_path)
    assert index.mode == "bm25" and index.search("SYNTHETIC TEST HOTEL")
    monkeypatch.setenv("RATE_TRUTH_RETRIEVAL", "bm25")
    assert Retriever(records).mode == "bm25"


def test_retrieval_expected_sets_are_recomputed_independently():
    records = Cards(Catalog()).records
    cases = json.loads((ROOT / "eval/retrieval_queries.json").read_text())
    assert len(cases) == 30
    for case in cases:
        rule = case["rule"]
        expected = []
        for identifier, record in records.items():
            hotel = record["hotel"]
            if rule["near_area"] and hotel["area"] != "near " + rule["near_area"]:
                continue
            if rule["kind"] == "stars":
                relevant = hotel["stars"] == rule["bound"]
            else:
                place = hotel["nearest_" + rule["kind"]]
                relevant = place and place["metres"] <= rule["bound"]
            if relevant:
                expected.append(identifier)
        assert sorted(expected) == case["expected_hotel_ids"]


@pytest.mark.parametrize(
    "fault",
    [
        "stale_cache",
        "missing_discount",
        "los_mismatch",
        "taxes_fees_omitted",
        "hotel_not_listed",
        "tax_rule_change_missed",
    ],
)
def test_real_catalog_faults_have_controls_and_realistic_scores(fault):
    report = audit(RateEngine(), faults=[fault])
    assert 0.6 <= report["score"] <= 0.9
    assert report["detection"]["precision"] == report["detection"]["recall"] == 1
    assert {s["nights"] for s in report["samples"]} == {1, 2, 3, 4, 7}
    weekdays = {date.fromisoformat(s["checkin"]).weekday() for s in report["samples"]}
    assert weekdays.intersection({4, 5}) and weekdays - {4, 5}
    if fault == "hotel_not_listed":
        assert 2 <= len({s["hotel_id"] for s in report["samples"] if s["injected"]}) <= 3


@pytest.mark.parametrize("coastal", [True, False, None])
def test_relief_fault_phase_two_requires_known_noncoastal(engine, hotel, coastal):
    engine.catalog._hotels = {hotel.id: hotel.model_copy(update={"coastal": coastal})}
    report = audit(engine, faults=["tax_rule_change_missed"])
    injected = [s for s in report["samples"] if s["injected"]]
    assert all("2026-04-01" <= s["checkin"] <= "2026-09-30" for s in injected)
    phase_two = [s for s in injected if s["checkin"] >= "2026-07-01"]
    assert bool(phase_two) is (coastal is False)

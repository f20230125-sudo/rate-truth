from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from rate_truth.accuracy.classify import classify, matches
from rate_truth.accuracy.faults import FAULTS, OFFICIAL, PRESS, inject
from rate_truth.accuracy.sampler import audit
from rate_truth.contract import folio
from rate_truth.feeds.hotel_list import build as build_list
from rate_truth.supplier.models import dubai_today


def test_clean_accuracy_and_no_persistent_faults(engine):
    clean = audit(engine, n=5, seed=42)
    assert clean["score"] == 1 and not clean["by_reason"]
    assert "not Google's score" in clean["definition"]
    assert all(s["feed"]["rate_id"] == s["landing"]["rate_id"] for s in clean["samples"])
    dirty = audit(engine, n=1, seed=42, faults=["taxes_fees_omitted"])
    assert dirty["score"] == 0
    repeat = audit(engine, n=5, seed=42)
    assert repeat["score"] == 1 and not repeat["faults"]


@pytest.mark.parametrize("fault", FAULTS, ids=lambda f: f["id"])
def test_each_fault_detected_from_evidence(engine, fault):
    report = audit(engine, n=30, faults=[fault["id"]])
    assert any(s["injected"] for s in report["samples"])
    assert any(not s["injected"] for s in report["samples"])
    assert report["detection"]["precision"] == 1
    assert report["detection"]["recall"] == 1
    for sample in report["samples"]:
        if not sample["injected"]:
            assert sample["detected_reason"] is None and sample["match"]
            continue
        assert sample["detected_reason"] == fault["id"]
        assert sample["reason"] == fault["google_reason"]
        assert sample["evidence"]
        # Rounding is diagnosed but remains within our advertised tolerance.
        assert sample["match"] is (fault["id"] == "currency_rounding")
        if fault["id"] == "tax_rule_change_missed":
            assert "2026-04-01" <= sample["checkin"] <= "2026-09-30"
            assert (
                OFFICIAL in sample["evidence"]
            )  # Public rule evidence, no injector press metadata.
            labels = {i["label"] for i in sample["landing"]["lines"]}
            assert {"Municipality fee", "Tourism Dirham"} <= labels
    assert {s["url"] for s in FAULTS[-1]["sources"]} == {PRESS, OFFICIAL}
    assert "https://" not in FAULTS[-1]["description"]


def test_score_tolerance_edges_and_itinerary(engine, hotel):
    landing = folio(engine.quote(hotel, dubai_today(), 1, 2), hotel)
    feed = deepcopy(landing)
    tolerance = max(Decimal(1), Decimal(landing["total"]) * Decimal(".01"))
    feed["total"] = str(Decimal(landing["total"]) + tolerance)
    assert matches(feed, landing)
    feed["total"] = str(Decimal(feed["total"]) + Decimal(".01"))
    assert not matches(feed, landing)
    assert not matches(landing, landing, hotel_list_xml=build_list([]).xml)
    changed = {**landing, "nights": 2}
    assert not matches(changed, landing)


def test_insufficient_evidence_is_not_overclaimed(engine, hotel):
    landing = folio(engine.quote(hotel, dubai_today(), 1, 2), hotel)
    changed = {**landing, "total": str(Decimal(landing["total"]) + 200)}
    result = classify(changed, landing)
    assert result["reason"] == "MISMATCH_REASON_UNSPECIFIED"
    assert result["diagnosis"] is None
    partial, _ = inject(landing, "tax_rule_change_missed")
    # Without a policy record, this is just missing tax evidence.
    assert classify(partial, landing)["diagnosis"] == "taxes_fees_omitted"


@pytest.mark.parametrize("n", [0, 101, True])
def test_audit_bounds(engine, n):
    with pytest.raises(ValueError):
        audit(engine, n=n)


def test_historical_replay_explicit_and_no_historical_holds(client, hotel):
    params = {"hotel_id": hotel.id, "checkin": "2026-05-12", "nights": 1, "guests": 2}
    assert client.get("/quote", params=params).status_code == 422
    historical = client.get("/quote", params={**params, "as_of": "2026-05-01"})
    assert historical.status_code == 200
    assert historical.json()["line_items"][1]["remittance_status"] == "remittance_exempt"
    assert (
        client.post("/holds", json={**params, "as_of": "2026-05-01", "confirm": True}).status_code
        == 422
    )
    assert date.fromisoformat(historical.json()["checkin"]) < dubai_today()

"""Validate the actual M0 artifact independently of synthetic unit fixtures."""

import hashlib
import json
import runpy
from collections import Counter
from datetime import datetime

from fastapi.testclient import TestClient

from rate_truth.settings import ROOT
from rate_truth.supplier.booking_api import create_app
from rate_truth.supplier.catalog import Catalog
from rate_truth.supplier.models import dubai_today
from rate_truth.supplier.rates import RateEngine


def test_snapshot_counts_metadata_and_estimates():
    folder = ROOT / "data" / "osm"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    hotels_doc = json.loads((folder / "hotels.json").read_text(encoding="utf-8"))
    pois_doc = json.loads((folder / "pois.json").read_text(encoding="utf-8"))
    hotels, pois = hotels_doc["hotels"], pois_doc["pois"]
    assert hotels and pois
    for payload in (hotels_doc, pois_doc, manifest):
        assert payload["licence"] == "ODbL-1.0"
        assert datetime.fromisoformat(payload["fetched_at"]).tzinfo is not None
        assert payload["fetched_at"] == manifest["fetched_at"]
        assert payload["query_sha256"] == manifest["query_sha256"]
    query = runpy.run_path(str(ROOT / "scripts" / "fetch_osm.py"))["QUERY"]
    assert hashlib.sha256(query.encode()).hexdigest() == manifest["query_sha256"]
    assert (folder / "query.overpass").read_text(encoding="utf-8") == query
    assert len({h["id"] for h in hotels}) == len(hotels)
    assert all(h["name"].strip() for h in hotels)
    for h in hotels:
        if h["stars"] is None:
            assert h["stars_estimated"] == 3
            assert h["stars_estimation_method"] == "unknown_category_default_3_v1"
        else:
            assert h["stars_tag"] == str(h["stars"])
            assert h["stars_estimated"] is None
    counts = manifest["counts"]
    assert counts["hotels_kept"] == len(hotels)
    assert counts["hotels_with_stars_tag"] == sum(h["stars_tag"] is not None for h in hotels)
    assert counts["hotels_with_valid_stars"] == sum(h["stars"] is not None for h in hotels)
    actual_pois = Counter(t for p in pois for t in p["types"])
    assert counts["pois_by_type"] == dict(actual_pois)
    assert set(actual_pois) == {
        "metro",
        "beach",
        "dubai_mall",
        "burj_khalifa",
        "dxb",
        "dwc",
        "expo_city",
        "dubai_marina",
        "old_dubai",
    }


def test_real_snapshot_supplier_landing_smoke():
    catalog = Catalog()
    engine = RateEngine(catalog=catalog)
    with TestClient(create_app(engine)) as client:
        listing = client.get("/hotels", params={"limit": 1})
        assert listing.status_code == 200
        hotel_id = listing.json()["hotels"][0]["id"]
        response = client.get(
            "/quote",
            params={
                "hotel_id": hotel_id,
                "checkin": dubai_today().isoformat(),
                "nights": 3,
                "guests": 2,
            },
        )
        assert response.status_code == 200
        assert response.json()["synthetic"] and response.json()["rate_id"]
        direct = engine.quote(hotel_id, dubai_today(), 3, 2)
        assert response.json()["total"] == direct["total"]
        assert response.json()["rate_id"] == direct["rate_id"]

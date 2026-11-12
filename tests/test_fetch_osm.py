import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "fetch_osm", Path(__file__).resolve().parents[1] / "scripts" / "fetch_osm.py"
)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def test_snapshot_normalization_and_provenance():
    raw = {
        "osm3s": {"timestamp_osm_base": "2026-11-11T00:00:00Z"},
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 25,
                "lon": 55,
                "tags": {
                    "tourism": "hotel",
                    "name": "TEST ONLY",
                    "stars": "4",
                    "website": "https://example.test",
                },
            },
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 25, "lon": 55},
                "tags": {"tourism": "hotel", "name": "TEST UNKNOWN"},
            },
            {"type": "node", "id": 3, "lat": 25, "lon": 55, "tags": {"tourism": "hotel"}},
            {
                "type": "node",
                "id": 4,
                "lat": 25,
                "lon": 55,
                "tags": {"railway": "station", "station": "subway", "name": "TEST METRO"},
            },
            {
                "type": "node",
                "id": 5,
                "lat": 25,
                "lon": 55,
                "tags": {"tourism": "hotel", "name": "TEST INVALID", "stars": "luxury"},
            },
        ],
    }
    hotels, pois, manifest = fetch.normalize(raw, "2026-11-11T10:00:00Z")
    assert len(hotels["hotels"]) == 3
    known, invalid, unknown = hotels["hotels"]
    assert known["stars"] == 4 and known["stars_estimated"] is None
    assert known["website"] == "https://example.test"
    assert unknown["stars"] is None and unknown["stars_estimated"] == 3
    assert unknown["stars_estimation_method"] == "unknown_category_default_3_v1"
    assert invalid["stars_tag"] == "luxury" and invalid["stars"] is None
    assert pois["pois"][0]["types"] == ["metro"]
    assert manifest["counts"]["hotels_without_name_dropped"] == 1
    assert manifest["counts"]["hotels_with_stars_tag"] == 2
    assert hotels["licence"] == "ODbL-1.0" and hotels["fetched_at"]
    assert 'ISO3166-2"="AE-DU' in fetch.QUERY


@pytest.mark.parametrize("raw", [{"elements": []}, {"elements": [], "remark": "runtime error"}])
def test_incomplete_responses_do_not_become_snapshots(raw):
    with pytest.raises(ValueError):
        fetch.normalize(raw, "2026-11-11T10:00:00Z")


@pytest.mark.parametrize(
    "tags,kind",
    [
        ({"natural": "beach"}, "beach"),
        ({"name:en": "Burj Khalifa", "building": "yes"}, "burj_khalifa"),
        ({"name": "Dubai Mall", "shop": "mall"}, "dubai_mall"),
        ({"iata": "DXB", "aeroway": "aerodrome"}, "dxb"),
        ({"iata": "DWC", "aeroway": "aerodrome"}, "dwc"),
        ({"name": "Expo City Dubai", "place": "suburb"}, "expo_city"),
        ({"name": "Dubai Marina", "place": "suburb"}, "dubai_marina"),
        ({"name": "Dubai Museum", "tourism": "museum"}, "old_dubai"),
    ],
)
def test_requested_poi_types(tags, kind):
    assert kind in fetch.poi_types(tags)


def test_similarly_named_road_is_not_a_landmark():
    assert fetch.poi_types({"name": "Al Fahidi Street", "highway": "residential"}) == []

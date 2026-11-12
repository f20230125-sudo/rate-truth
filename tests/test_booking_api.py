import pytest
from fastapi.testclient import TestClient

from rate_truth.settings import ORIGIN
from rate_truth.supplier.booking_api import create_app
from rate_truth.supplier.catalog import Catalog
from rate_truth.supplier.models import dubai_today
from rate_truth.supplier.rates import RateEngine


def params(**overrides):
    return {
        "hotel_id": "node/123",
        "checkin": dubai_today().isoformat(),
        "nights": 2,
        "guests": 2,
        **overrides,
    }


def test_catalog_and_landing_price(client, engine, hotel):
    response = client.get("/hotels")
    assert response.status_code == 200 and response.json()["synthetic"]
    # No HTML response; OSM names are returned only as untrusted JSON strings.
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["hotels"][0]["name"] == hotel.name
    details = client.get("/hotels/node/123").json()
    assert len(details["room_types"]) == 3 and len(details["plans"]) == 4
    landing = client.get("/quote", params=params()).json()
    direct = engine.quote(hotel, dubai_today(), 2, 2)
    assert landing["total"] == direct["total"] and landing["rate_id"] == direct["rate_id"]
    assert landing["computed_at"] and "SYNTHETIC" in landing["disclosure"]


def test_inventory_and_confirmed_mock_hold(client):
    before = client.get("/availability", params=params()).json()
    response = client.post("/holds", json={**params(), "confirm": True})
    assert response.status_code == 201
    hold = response.json()
    assert hold["mock_only"] and not hold["booked"] and hold["synthetic"]
    assert hold["rate_id"] == hold["quote"]["rate_id"]
    after = client.get("/availability", params=params()).json()
    assert after["available"] == before["available"] - 1


@pytest.mark.parametrize("value", [False, None, "true", 1, "yes"])
def test_unconfirmed_hold_does_not_mutate(client, value):
    before = client.get("/availability", params=params()).json()
    response = client.post("/holds", json={**params(), "confirm": value})
    assert response.status_code == 422 and response.json()["error"]
    assert client.get("/availability", params=params()).json() == before


@pytest.mark.parametrize("endpoint", ["/quote", "/availability"])
@pytest.mark.parametrize(
    "override",
    [
        {"nights": 0},
        {"nights": 31},
        {"guests": 9},
        {"guests": 3, "room_type": "standard"},
        {"hotel_id": "../../.env"},
        {"checkin": "2020-01-01"},
        {"checkin": "2027-11-12"},
        {"plan": "bogus"},
        {"room_type": "bogus"},
        {"extra": "forbidden"},
    ],
)
def test_endpoint_validation(client, endpoint, override):
    response = client.get(endpoint, params=params(**override))
    assert response.status_code == 422
    expected = {
        "nights": "nights_out_of_range",
        "guests": "guests_out_of_range",
        "hotel_id": "unknown_hotel",
        "checkin": "date_out_of_range",
    }
    assert response.json()["error"]["code"] == expected.get(next(iter(override)), "invalid_input")
    assert response.json()["error"]["field"]
    assert response.json()["error"]["rule"]
    assert "traceback" not in response.text.lower()


def test_unknown_ids_invalid_bodies_and_bounds(client):
    assert client.get("/quote", params=params(hotel_id="node/999")).status_code == 404
    assert client.get("/hotels/node/999").status_code == 404
    assert client.get("/hotels/not-an-osm-id").status_code == 422
    assert client.get("/hotels", params={"limit": 101}).status_code == 422
    assert client.get("/hotels", params={"offset": -1}).status_code == 422
    assert client.get("/hotels", params={"name": "x" * 201}).status_code == 422
    assert client.post("/holds", content="{broken").status_code == 422
    assert client.post("/holds", json=[True]).status_code == 422
    assert client.post("/holds", json=params()).status_code == 422
    assert (
        client.post("/holds", json={**params(), "confirm": True, "payment": "no"}).status_code
        == 422
    )


def test_cors_is_our_origin_and_cross_origin_hold_cannot_mutate(client):
    response = client.get("/hotels", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN
    before = client.get("/availability", params=params()).json()
    response = client.post(
        "/holds", json={**params(), "confirm": True}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    assert client.get("/availability", params=params()).json() == before


def test_missing_snapshot_is_explicit_503(tmp_path):
    engine = RateEngine(catalog=Catalog(tmp_path / "missing.json"))
    with TestClient(create_app(engine)) as client:
        response = client.get("/hotels")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "data_unavailable"
        assert str(tmp_path) not in response.text


def test_sold_out_is_409(client):
    available = client.get("/availability", params=params()).json()["available"]
    for _ in range(available):
        assert client.post("/holds", json={**params(), "confirm": True}).status_code == 201
    response = client.post("/holds", json={**params(), "confirm": True})
    assert response.status_code == 409 and response.json()["error"]["code"] == "sold_out"


def test_hold_body_size_is_bounded(client):
    response = client.post("/holds", content="x" * 9000)
    assert response.status_code == 413


def test_chunked_body_cannot_bypass_size_limit(client):
    chunks = (b"x" * 4000 for _ in range(3))
    response = client.post("/holds", content=chunks)
    assert response.status_code == 413


@pytest.mark.parametrize("field", ["nights", "guests"])
def test_json_boolean_is_not_a_guest_or_night_count(client, field):
    response = client.post("/holds", json={**params(), "confirm": True, field: True})
    assert response.status_code == 422


def test_unknown_list_parameters_and_http_errors_are_structured(client):
    response = client.get("/hotels", params={"unknown": "invalid"})
    assert response.status_code == 422 and response.json()["error"]
    assert client.get("/unknown-route").json()["error"]["code"] == "http_error"
    assert client.post("/quote").json()["error"]["code"] == "http_error"

"""Explicit synthetic fixtures for unit tests; never used as an OSM fallback."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from rate_truth.supplier.booking_api import create_app
from rate_truth.supplier.catalog import Catalog
from rate_truth.supplier.inventory import Inventory
from rate_truth.supplier.models import Hotel
from rate_truth.supplier.rates import RateEngine


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 11, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("rate_truth.supplier.models.datetime", FrozenDatetime)


@pytest.fixture
def hotel():
    return Hotel(
        id="node/123",
        name="SYNTHETIC TEST HOTEL <script>alert(1)</script>",
        lat=25.20,
        lon=55.28,
        stars=5,
        stars_tag="5",
    )


@pytest.fixture
def engine(tmp_path, hotel):
    path = tmp_path / "hotels.json"
    path.write_text(json.dumps({"hotels": [hotel.model_dump()]}), encoding="utf-8")
    return RateEngine(seed=2026, catalog=Catalog(path), market_calibration={})


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine)) as client:
        yield client


@pytest.fixture
def fixed_inventory():
    now = [datetime(2026, 11, 11, 10, tzinfo=UTC)]
    inventory = Inventory(seed=2026, clock=lambda: now[0])
    return inventory, now


@pytest.fixture
def scripted_hold_replay(tmp_path, monkeypatch):
    """Keep hold-boundary unit tests independent of changing live model recordings."""
    from rate_truth.agent.replay import SUGGESTIONS

    directory = tmp_path / "replay"
    directory.mkdir()
    record = {
        "provenance": "scripted_test_fixture_not_live_recording",
        "message": SUGGESTIONS[2],
        "plan": [
            {"tool": "search_hotels", "args": {"checkin": "$today", "nights": 2, "limit": 1}},
            {"tool": "get_rates", "args": {
                "hotel_id": "$first", "checkin": "$today", "nights": 2,
            }},
        ],
    }
    (directory / "hold.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr("rate_truth.agent.replay.DIRECTORY", directory)

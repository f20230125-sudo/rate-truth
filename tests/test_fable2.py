"""Regression cases from independent review 2; no provider network access."""

import ast
import asyncio
import hashlib
import inspect
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from urllib.parse import urlencode

import httpx
import pytest
from fastapi.testclient import TestClient

from rate_truth.accuracy import classify as classifier
from rate_truth.accuracy.sampler import audit
from rate_truth.market.base import MarketError
from rate_truth.market.matching import match_many, match_property, token_set_ratio
from rate_truth.market.storage import read_json, write_json
from rate_truth.market.xotelo import API, Xotelo, parse_rates
from rate_truth.mcp_server.service import Gateway, GatewayError
from rate_truth.supplier.models import Hotel
from rate_truth.web.app import create_app

PAIRS = [
    ("ARCADIA HOTEL apartment", "Sitara Hotel Apartment", False),
    ("ana palace hotel", "Spring Palace Hotel Apartments", False),
    ("Flora Park Hotel Apartments", "Flora Creek Deluxe Hotel Apartments", False),
    ("Bay Square 13", "Bay Square 9", False),
    ("London Crown", "London Crown 2 Hotel Apartments", False),
    ("Sun & Sands Hotel", "Sun And Sands Plaza Hotel", False),
    ("ibis Deira City Centre Hotel Dubai", "Novotel Deira City Centre Hotel Dubai", False),
    ("Golden Sands 3", "Golden Sands 5", False),
    ("Golden Sands Hotel Apartments 3", "Golden Sands Hotel Apartments 10", False),
    ("Hilton Dubai Jumeirah", "Hilton Dubai The Walk", False),
    ("Premier Inn", "Premier Inn Dubai International Airport", False),
    ("Rove", "Rove City Walk", False),
    ("ibis", "ibis Styles Dubai Jumeirah", False),
    ("Grand Hotel", "Royal Grand Suite Hotel", False),
    ("City Hotel Apartment", "Star Hotel Apartment", False),
    ("Hotel Inn", "Budget Inn", False),
    ("Premier Inn Dubai Al Jaddaf", "Premier Inn Dubai Silicon Oasis", False),
    ("Flora Creek", "Flora Creek Deluxe", False),
    ("Palace Hotel", "Royal Hotel", False),
    ("Ibis One Central", "Novotel One Central", False),
    ("Four Points by Sheraton Downtown", "Four Points by Sheraton Bur Dubai", False),
    ("Atlantis The Palm", "Atlantis The Royal", False),
    ("Address Downtown", "Address Dubai Mall", False),
    ("Example Marina", "Exampel Marina", False),
    ("Kempinski Palm Jumeirah Residences", "Kempinski Hotel Palm Jumeirah", False),
    ("Sun & Sands Hotel", "Sun and Sands Hotel", True),
    ("Arcadia HOTEL apartment", "Arcadia Hotel Apartments", True),
    ("London Crown", "London Crown Hotel Apartments", True),
    ("Bay Square 13", "Bay Square 13 Dubai", True),
    ("Golden Sands 3", "Golden Sands 3 Hotel Apartments", True),
    ("Flora Creek Deluxe", "Flora Creek Deluxe Hotel Apartments", True),
    ("ANA PALACE HOTEL", "Ana Palace", True),
    ("Ibis Deira City Centre", "ibis Deira City Centre Hotel Dubai", True),
    ("Rove City Walk", "Rove City Walk Dubai UAE", True),
    ("Premier Inn Al Jaddaf", "Premier Inn Dubai Al Jaddaf", True),
    ("Marina Example Hotel", "Example Marina Hotel", True),
    ("Hôtel Étoile", "Hotel Etoile", True),
    ("Hilton Dubai Jumeirah", "Hilton Jumeirah", True),
    ("Palace", "The Palace Hotel", True),
    ("Royal Residence", "Royal Residences Dubai", True),
    ("Sitara Inn", "Sitara Suites", True),
    ("One & Only Royal Mirage", "One and Only Royal Mirage", True),
    ("Al-Jaddaf Rotana", "Al Jaddaf Rotana Dubai", True),
    ("Hyatt Regency", "Hyatt Regency Hotel LLC", True),
    ("Wyndham Marina", "Wyndham Dubai Marina", True),
    ("Jumeirah Beach", "Jumeirah Beach Resort", True),
    ("Radisson Blu Waterfront", "Radisson Blu Hotel Dubai Waterfront", True),
    ("Novotel World Trade Centre", "Novotel World Trade Centre Dubai", True),
    ("Sunrise 12", "Sunrise12 Apartments", True),
    ("emirates Concorde", "Emirates Concorde Hotel & Residence", True),
]


@pytest.mark.parametrize("left,right,expected", PAIRS)
def test_labelled_identity_pairs(left, right, expected):
    assert (token_set_ratio(left, right) >= 0.82) == expected


def test_ambiguous_provider_still_vetoes_osm():
    hotels = [Hotel(id=f"node/{i}", name="Sun and Sands Hotel", lat=25, lon=55) for i in (1, 2)]
    # One provider is ambiguous across OSM identities; it still vetoes the other key.
    hotels[1] = hotels[1].model_copy(update={"lat": 25.002})
    props = [
        {"key": "a", "name": "Sun and Sands Hotel", "geo": {"latitude": 25, "longitude": 55}},
        {"key": "b", "name": "Sun and Sands Hotel", "geo": {"latitude": 24.998, "longitude": 55}},
    ]
    assert not any(r["status"] == "matched" for r in match_many(props, hotels))


def test_true_sun_sands_does_not_match_plaza():
    hotel = Hotel(id="way/436231402", name="Sun & Sands Hotel", lat=25, lon=55)
    assert (
        match_property(
            {"name": "Sun And Sands Plaza Hotel", "geo": {"latitude": 25, "longitude": 55}}, [hotel]
        )["status"]
        == "unmatched"
    )


def test_public_mcp_host_and_no_redirect(engine, monkeypatch):
    monkeypatch.setenv("RATE_TRUTH_HOSTS", "rate-truth.vercel.app,*.vercel.app")
    monkeypatch.setenv("VERCEL_URL", "rate-truth-preview.vercel.app")
    with TestClient(create_app(engine, force_replay=True)) as client:
        headers = {"Host": "rate-truth.vercel.app", "Accept": "application/json, text/event-stream"}
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        for path in ("/mcp", "/mcp/"):
            assert (
                client.post(path, json=body, headers=headers, follow_redirects=False).status_code
                == 200
            )
        headers["Host"] = "rate-truth-preview.vercel.app"
        assert client.post("/mcp", json=body, headers=headers).status_code == 200
        headers["Origin"] = "https://evil.example"
        assert client.post("/mcp", json=body, headers=headers).status_code == 403
        headers["Host"] = "evil.example"
        headers.pop("Origin")  # Isolate Host validation from the existing Origin rejection.
        assert client.post("/mcp", json=body, headers=headers).status_code == 421


def test_web_cannot_steal_token(engine, hotel):
    app = create_app(engine, force_replay=True)
    offer = app.state.gateway.get_rates(app.state.gateway.stay(hotel.id, date(2026, 12, 1)))
    body = {"rate_id": offer["folio"]["rate_id"], "confirm": True}
    with TestClient(app) as client:
        assert client.post("/api/holds", json=body).status_code == 422
        assert client.post("/api/holds", json={**body, "hold_token": "x" * 40}).status_code == 422
        assert (
            client.post("/api/holds", json={**body, "hold_token": offer["hold_token"]}).status_code
            == 201
        )


def test_cross_instance_signed_hold(engine, hotel, monkeypatch):
    monkeypatch.setenv("RATE_TRUTH_SECRET", "test-only-stable-secret")
    first, second = Gateway(engine), Gateway(engine)
    offer = first.get_rates(first.stay(hotel.id, date(2026, 12, 1)))
    result = second.hold(offer["folio"]["rate_id"], offer["hold_token"], True)
    assert result["mock"] and result["hold_id"].startswith("mock_")
    with pytest.raises(GatewayError):
        second.hold(offer["folio"]["rate_id"], offer["hold_token"], True)
    with pytest.raises(GatewayError):
        first.hold(offer["folio"]["rate_id"], offer["hold_token"][:-1] + "!", True)


@pytest.mark.parametrize("trusted,expected", [(False, 429), (True, 200)])
def test_proxy_buckets(engine, monkeypatch, trusted, expected):
    monkeypatch.setenv("RATE_TRUTH_TRUST_PROXY", str(trusted).lower())
    with TestClient(create_app(engine, force_replay=True)) as client:
        for i in range(61):
            response = client.get(
                "/api/taxes", headers={"x-vercel-forwarded-for": f"192.0.2.{i + 1}, 10.0.0.1"}
            )
        assert response.status_code == expected


def test_audit_multiple_faults_order_independent(engine):
    faults = ["stale_cache", "taxes_fees_omitted"]
    left = audit(engine, n=60, faults=faults)
    right = audit(engine, n=60, faults=list(reversed(faults)))
    counts = Counter(s["injected"] for s in left["samples"])
    assert all(counts[f] > 0 for f in faults)
    assert [s["injected"] for s in left["samples"]] == [s["injected"] for s in right["samples"]]


def test_classifier_has_no_injector_dependency():
    tree = ast.parse(inspect.getsource(classifier))
    assert not any(
        isinstance(n, ast.ImportFrom) and "faults" in (n.module or "") for n in ast.walk(tree)
    )
    assert "policy_evidence" not in inspect.signature(classifier.classify).parameters


def test_serialized_audit_evidence_without_metadata(engine):
    from rate_truth.accuracy.faults import FAULT_IDS

    report = audit(engine, n=100, faults=sorted(FAULT_IDS))
    assert {s["injected"] for s in report["samples"]} >= FAULT_IDS
    for s in report["samples"]:
        stripped = json.loads(json.dumps({k: s[k] for k in ("feed", "landing", "hotel_list_xml")}))
        assert (
            classifier.classify(**stripped, tax_rules=engine.taxes.data)["diagnosis"]
            == s["detected_reason"]
        )


def test_xotelo_cache_during_slow_network(tmp_path):
    entered, release = Event(), Event()
    now = datetime.now(UTC).isoformat()
    params = {"x": "warm"}
    url = API + "rates?" + urlencode(sorted(params.items()))
    cache = tmp_path / "cache" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    saved = {"url": url, "fetched_at": now, "response": {"result": {}}}
    write_json(cache, saved)

    def handler(request):
        entered.set()
        release.wait(6)
        return httpx.Response(200, json={"result": {}})

    x = Xotelo(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)))
    with ThreadPoolExecutor(2) as pool:
        slow = pool.submit(x.request, "rates", {"x": "slow"})
        assert entered.wait(2)
        try:
            hit = pool.submit(x.request, "rates", params)
            assert hit.result(timeout=1) == saved
        finally:
            release.set()
        slow.result()


def test_storage_permission_retry(tmp_path, monkeypatch):
    import os

    original, calls = os.replace, []

    def busy(*args):
        calls.append(args)
        if len(calls) < 3:
            raise PermissionError("Windows reader sharing violation")
        return original(*args)

    monkeypatch.setattr(os, "replace", busy)
    write_json(tmp_path / "race.json", {"ok": True})
    assert read_json(tmp_path / "race.json") == {"ok": True}
    assert len(calls) == 3


def test_live_identity_fields_not_saved_match():
    hotel = {"key": "k", "name": "Sun and Sands Hotel", "geo": {"latitude": 25, "longitude": 55}}
    payload = {
        "result": {
            "name": "Sun And Sands Plaza Hotel",
            "geo": hotel["geo"],
            "hotel_key": "k",
            "rates": [{"rate": 100}],
        }
    }
    obs = parse_rates(
        payload, hotel, date(2026, 12, 1), date(2026, 12, 3), datetime.now(UTC).isoformat()
    )
    assert obs.name == "Sun And Sands Plaza Hotel"


def test_response_size_and_refund_metadata(engine, hotel):
    from rate_truth.feeds.transaction import build
    from rate_truth.feeds.validate import parse

    gateway = Gateway(engine)
    results = gateway.search(nights=30)
    assert len(results["items"][0]["from_folio"]["lines"]) <= 5
    artifact = build(engine, [gateway.stay(hotel.id, date(2026, 12, 1))])
    refund = parse(artifact.xml).find("Result/Refundable")
    assert refund.get("refundable_until_days") == "1"
    assert refund.get("refundable_until_time") == "18:00:00"


def test_market_default_cached_and_live_limit(engine, hotel, monkeypatch, tmp_path):
    monkeypatch.setenv("RATE_TRUTH_MARKET_DIR", str(tmp_path))
    app = create_app(engine, force_replay=True)
    with TestClient(app) as client:
        assert (
            client.get("/api/market", params={"hotel_id": hotel.id}).json()["live_requested"]
            is False
        )
        for _ in range(7):
            response = client.get("/api/market", params={"hotel_id": hotel.id, "live": "true"})
        assert response.status_code == 429


def test_provider_url_schemes():
    from rate_truth.market.base import Observation

    observation = json.loads(Path("tests/fixtures/xotelo/rates.json").read_text())
    prop = {
        "key": "k",
        "name": "Example",
        "url": "javascript:alert(1)",
        "geo": {"latitude": 25, "longitude": 55},
    }
    obs = parse_rates(
        observation, prop, date(2026, 12, 1), date(2026, 12, 2), datetime.now(UTC).isoformat()
    )
    assert obs.link is None
    assert Observation(**{**obs.output(), "link": "data:text/html,test"}).output()["link"] is None


def test_retrieval_metrics_are_not_capped_by_relevant_set():
    from eval.retrieval import metrics

    result = metrics(list(range(20)), set(range(20)))
    assert result == {"hit_at_5": 1, "precision_at_5": 1, "r_precision": 1, "ndcg_at_10": 1}
    assert metrics([99], {1, 2}) == {
        "hit_at_5": 0,
        "precision_at_5": 0,
        "r_precision": 0,
        "ndcg_at_10": 0,
    }
    short = metrics([1], {1, 2})
    assert short["precision_at_5"] == 0.2 and short["r_precision"] == 0.5
    assert 0 < short["ndcg_at_10"] < 1


def test_numeric_metro_request_routes_to_filter(engine):
    from rate_truth.agent.llm.store import Completion
    from rate_truth.agent.loop import Agent
    from rate_truth.mcp_server.server import create_server

    class LLM:
        calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            action = {
                "action": "call",
                "tool": "recommend_hotels",
                "args": {"query": "within 300 m of a metro", "checkin": "2026-12-01", "limit": 5},
            }
            if self.calls > 1:
                action = {"action": "answer", "text": "Only sourced metro distances are available."}
            return Completion(json.dumps(action), 0, 0, "test")

    gateway = Gateway(engine)
    agent = Agent(create_server(gateway), gateway, force_replay=True)

    async def run():
        return [
            (event, data)
            async for event, data in agent.stream("Find hotels within 300 m of a metro", llm=LLM())
        ]

    events = asyncio.run(run())
    trace = next(data for event, data in events if event == "trace")
    assert trace["tool"] == "search_hotels" and trace["args"]["near_metro"] == 300
    assert trace["ok"]


def test_xotelo_unverified_multinight_never_calls_provider(tmp_path):
    requests = []
    xotelo = Xotelo(
        tmp_path,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json={"result": {}})
            )
        ),
    )
    with pytest.raises(MarketError, match="multi-night"):
        xotelo.observe({"key": "k"}, date(2026, 12, 1), date(2026, 12, 3))
    assert requests == []


def test_signed_tokens_reject_different_secret_and_expiry(engine, hotel, monkeypatch):
    monkeypatch.setenv("RATE_TRUTH_SECRET", "first-test-secret")
    now = [datetime(2026, 11, 11, tzinfo=UTC)]
    gateway = Gateway(engine, clock=lambda: now[0])
    offer = gateway.get_rates(gateway.stay(hotel.id, date(2026, 12, 1)))
    monkeypatch.setenv("RATE_TRUTH_SECRET", "second-test-secret")
    with pytest.raises(GatewayError):
        Gateway(engine).hold(offer["folio"]["rate_id"], offer["hold_token"], True)
    now[0] += timedelta(minutes=15)
    with pytest.raises(GatewayError):
        gateway.hold(offer["folio"]["rate_id"], offer["hold_token"], True)


def test_mcp_full_catalog_xml_serialized_once():
    from rate_truth.mcp_server.server import create_server

    async def run():
        return await create_server().call_tool("build_hotel_list_feed", {})

    result = asyncio.run(run())
    assert not result.is_error
    assert result.content == [] and len(result.structured_content["items"]) == 2
    assert len(result.model_dump_json(by_alias=True).encode()) < 3_000_000


def test_json_readers_and_writers_share_lock(tmp_path):
    path = tmp_path / "concurrent.json"
    write_json(path, {"value": 0, "copy": 0})

    def worker(index):
        for value in range(15):
            write_json(path, {"value": value + index, "copy": value + index})
            result = read_json(path)
            assert result["value"] == result["copy"]

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(worker, range(4)))

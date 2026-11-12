"""Offline fixtures plus network transports; never contact a real provider."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import Client

from rate_truth.contract import folio
from rate_truth.market.base import SERPAPI, XOTELO, MarketError
from rate_truth.market.budget import Budget
from rate_truth.market.calibrate import back_compute, derive_anchors
from rate_truth.market.matching import match_many, match_property, token_set_ratio
from rate_truth.market.repository import MarketRepository
from rate_truth.market.serpapi import SerpApi, parse_property, properties_from
from rate_truth.market.service import MarketService, parity
from rate_truth.market.storage import read_json, scrub, write_json
from rate_truth.market.xotelo import Xotelo, parse_rates
from rate_truth.mcp_server.server import create_server
from rate_truth.mcp_server.service import Gateway
from rate_truth.supplier.models import Hotel, money
from rate_truth.supplier.rates import RateEngine
from rate_truth.web.app import create_app
from scripts.fetch_market import QUERIES, fetch_snapshot, stay_dates

FIXTURES = Path(__file__).parent / "fixtures"
DAY = date(2026, 11, 18)
STAMP = "2026-11-11T12:00:00+00:00"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def market_engine(engine):
    engine.catalog._hotels = {
        "node/123": Hotel(id="node/123", name="Example Marina Hotel", lat=25.2, lon=55.28, stars=5)
    }
    return engine


@pytest.fixture
def fake_time():
    now = [datetime.fromisoformat(STAMP)]

    def sleep(seconds):
        now[0] += timedelta(seconds=seconds)

    return now, lambda: now[0], sleep


def xotelo_observation():
    return parse_rates(
        fixture("xotelo/rates.json"),
        fixture("xotelo/list.json")["result"]["list"][0],
        DAY,
        DAY + timedelta(days=1),
        STAMP,
    )


def serp_observation():
    return parse_property(
        fixture("serpapi/search.json")["properties"][0],
        DAY,
        DAY + timedelta(days=1),
        STAMP,
        "Dubai Marina hotels",
    )


def row(observation):
    return {
        "hotel_id": "node/123",
        "match_score": 1.0,
        "distance_m": 0,
        "observation": observation.output(),
    }


def test_recursive_scrub():
    saved = scrub(fixture("serpapi/search.json"), "FIXTURE_ONLY_SECRET")
    serialized = json.dumps(saved)
    assert "FIXTURE_ONLY_SECRET" not in serialized and "api_key=" not in serialized
    assert scrub(
        {"api_key": "secret", "nested": [{"API_KEY": "secret", "x": "secret"}]}, "secret"
    ) == {"nested": [{"x": "[redacted]"}]}


def test_budget_atomic_cap_rollover_and_no_refunds(tmp_path, fake_time):
    now, clock, _ = fake_time
    budget = Budget(tmp_path / "budget.json", clock)
    write_json(budget.path, {"month": "2026-11", "used": 210})

    def reserve(_):
        try:
            budget.reserve()
            return True
        except MarketError as exc:
            assert exc.code == "market_budget_exhausted"
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        assert sum(pool.map(reserve, range(30))) == 10
    assert budget.status()["used"] == 220 and budget.status()["remaining"] == 0
    now[0] = datetime(2026, 12, 1, tzinfo=UTC)
    assert budget.status()["used"] == 0
    assert budget.reserve() == {"month": "2026-12", "used": 1}


def test_budget_corruption_and_serverless_fail_closed(tmp_path, monkeypatch):
    budget = Budget(tmp_path / "budget.json")
    write_json(budget.path, {"month": "2026-11", "used": "invalid"})
    with pytest.raises(MarketError, match="invalid"):
        budget.reserve()
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("RATE_TRUTH_MARKET_PERSISTENT", raising=False)
    with pytest.raises(MarketError, match="persistent"):
        budget.reserve()


def test_no_key_does_not_reserve_or_call(tmp_path, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    budget = Budget(tmp_path / "budget.json")
    with pytest.raises(MarketError) as caught:
        SerpApi(budget=budget).search("Dubai", DAY, DAY + timedelta(days=1))
    assert caught.value.code == "market_key_missing"
    assert not budget.path.exists()


def test_serpapi_params_scrub_logging_and_budget(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SERPAPI_API_KEY", "FIXTURE_ONLY_SECRET")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=fixture("serpapi/search.json"))

    client = SerpApi(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        budget=Budget(tmp_path / "budget.json"),
    )
    with caplog.at_level(logging.INFO, logger="httpx"):
        result = client.search(
            "Dubai Marina hotels",
            DAY,
            DAY + timedelta(days=1),
            property_token="abc",
            next_page_token="page2",
        )
    assert requests[0].url.host == "serpapi.com"
    assert requests[0].url.params["api_key"] == "FIXTURE_ONLY_SECRET"
    assert requests[0].url.params["currency"] == "AED"
    assert requests[0].url.params["property_token"] == "abc"
    assert requests[0].url.params["next_page_token"] == "page2"
    assert "FIXTURE_ONLY_SECRET" not in json.dumps(result) + caplog.text
    assert "api_key=" not in json.dumps(result)
    assert client.budget.status()["used"] == 1


def test_serpapi_failure_reserves_and_does_not_expose_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "FAILURE_SECRET")
    budget = Budget(tmp_path / "budget.json")
    client = SerpApi(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
        budget=budget,
    )
    with pytest.raises(MarketError) as caught:
        client.search("Dubai", DAY, DAY + timedelta(days=1))
    assert "FAILURE_SECRET" not in str(caught.value)
    assert budget.status()["used"] == 1


def test_xotelo_original_usd_and_unknown_taxes():
    obs = xotelo_observation()
    assert obs.provider == XOTELO
    assert obs.amount_original == "100" and obs.amount_aed == "367.25"
    assert obs.aed_conversion["rate"] == "3.6725"
    assert obs.taxes_included is None and obs.lowest_all_in_aed is None
    assert obs.tax_label == "as shown by the booking site; taxes not stated"
    assert len(obs.per_source) == 3


def test_xotelo_all_pages_cache_ttl_pacing_and_ua(tmp_path, fake_time):
    now, clock, sleep = fake_time
    starts, requests = [], []

    def handler(request):
        starts.append(now[0])
        requests.append(request)
        assert request.headers["User-Agent"] == "rate-truth/0.1 (portfolio project)"
        assert "/search" not in request.url.path
        if request.url.path.endswith("/rates"):
            assert request.url.params["currency"] == "USD"
            return httpx.Response(200, json=fixture("xotelo/rates.json"))
        offset = int(request.url.params["offset"])
        assert int(request.url.params["limit"]) == 100
        records = [
            dict(fixture("xotelo/list.json")["result"]["list"][0], key=f"g295424-d{i}")
            for i in range(offset, min(offset + 100, 201))
        ]
        return httpx.Response(
            200, json={"error": None, "result": {"total_count": 201, "list": records}}
        )

    client = Xotelo(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)), clock, sleep)
    assert len(client.list_all()) == 3
    assert [int(r.url.params["offset"]) for r in requests] == [0, 100, 200]
    assert len(client.list_all()) == 3 and len(requests) == 3
    prop = fixture("xotelo/list.json")["result"]["list"][0]
    first = client.observe(prop, DAY, DAY + timedelta(days=1))
    assert client.observe(prop, DAY, DAY + timedelta(days=1)).fetched_at == first.fetched_at
    assert len(requests) == 4
    now[0] += timedelta(hours=6)
    assert client.observe(prop, DAY, DAY + timedelta(days=1)).fetched_at != first.fetched_at
    assert len(requests) == 5
    now[0] += timedelta(days=7)
    assert len(client.list_all()) == 3 and len(requests) == 8
    assert all((b - a).total_seconds() >= 1 for a, b in zip(starts, starts[1:], strict=False))
    assert len(list((tmp_path / "cache").glob("*.json"))) == 4


def test_xotelo_retry_at_most_once(tmp_path, fake_time):
    _, clock, sleep = fake_time
    calls = []

    def handler(request):
        calls.append(clock())
        return httpx.Response(503)

    client = Xotelo(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)), clock, sleep)
    with pytest.raises(MarketError):
        client.list_all()
    assert len(calls) == 2 and (calls[1] - calls[0]).total_seconds() >= 2


def test_matching_exact_fuzzy_far_missing_and_ambiguous(market_engine):
    hotels = list(market_engine.catalog.hotels.values())
    prop = fixture("xotelo/list.json")["result"]["list"][0]
    assert match_property(prop, hotels)["score"] == 1
    assert token_set_ratio("Example Marina Hotel", "Marina Example hotel") == 1
    fuzzy = {**prop, "name": "Exampel Marina Hotel"}
    assert match_property(fuzzy, hotels)["status"] == "unmatched"  # Typos require manual review.
    far = {**prop, "geo": {"latitude": 25.3, "longitude": 55.28}}
    assert match_property(far, hotels)["status"] == "unmatched"
    assert match_property({"name": prop["name"]}, hotels)["status"] == "unmatched"
    assert (
        match_property(prop, hotels + [hotels[0].model_copy(update={"id": "node/456"})])["status"]
        == "ambiguous"
    )
    assert all(
        r["status"] == "ambiguous"
        for r in match_many([prop, {**prop, "key": "different-property"}], hotels)
    )


def test_serpapi_parser_search_and_total_detail():
    obs = serp_observation()
    assert obs.provider == SERPAPI and obs.before_tax_aed == "400.00"
    assert obs.lowest_all_in_aed == "510.00" and obs.taxes_included is True
    assert obs.hotel_class == 5 and obs.per_source[0]["site"] == "Example booking site"
    detail = fixture("serpapi/detail.json")
    assert properties_from(detail) == [detail]
    parsed = parse_property(detail, DAY, DAY + timedelta(days=2), STAMP, "Dubai")
    assert parsed.before_tax_aed == "400.00" and parsed.lowest_all_in_aed == "510.00"
    assert (
        parse_property({"name": "missing coordinates"}, DAY, DAY + timedelta(days=1), STAMP, "x")
        is None
    )
    detail["total_rate"] = {"extracted_lowest": 1020}
    assert (
        parse_property(detail, DAY, DAY + timedelta(days=2), STAMP, "x").lowest_all_in_aed is None
    )


def test_calibration_precedence_median_and_tax_exclusion():
    x, s = xotelo_observation(), serp_observation()
    assert derive_anchors([row(x)])["anchors"]["node/123"]["anchor_aed"] == "403.98"
    anchor = derive_anchors([row(x), row(s)])["anchors"]["node/123"]
    assert anchor["anchor_aed"] == "400.00" and anchor["basis"] == "stated pre-tax"
    x.per_source[0]["tax_original"] = "20"
    assert derive_anchors([row(x)])["anchors"] == {}
    s.before_tax_aed = None
    assert derive_anchors([row(s)])["anchors"] == {}  # top-level override: published ADR fallback
    assert derive_anchors([{"observation": s.output()}])["anchors"] == {}


def test_back_compute_independent_arithmetic(market_engine):
    assert back_compute("1245", market_engine.taxes, DAY, 5) == {
        "amount": "1000.00",
        "basis": "derived",
        "residual_aed": "0.00",
    }
    assert back_compute("423.32", market_engine.taxes, DAY, 4)["amount"] == "333.33"


def test_anchor_reference_relative_factors_and_unmatched(market_engine):
    calibration = derive_anchors([row(serp_observation())])
    engine = RateEngine(catalog=market_engine.catalog, market_calibration=calibration)
    hotel = engine.catalog.get("node/123")
    anchored = engine.quote(hotel, DAY, 1, 2)
    assert anchored["base"] == "400.00"
    later = DAY + timedelta(days=45)
    reference = Decimal(market_engine.quote(hotel, DAY, 1, 2)["base"])
    # Relative factors compare before displayed rounding, with a one-fils bound.
    expected = money(Decimal(market_engine.quote(hotel, later, 1, 2)["base"]) * 400 / reference)
    assert abs(Decimal(engine.quote(hotel, later, 1, 2)["base"]) - expected) <= Decimal(".01")
    assert (
        "base anchored to Google Hotels (via SerpApi) price seen 2026-11-11"
        in folio(anchored, hotel)["lines"][0]["basis"]
    )
    other = hotel.model_copy(update={"id": "node/456"})
    assert engine.quote(other, DAY, 1, 2)["base"] == market_engine.quote(other, DAY, 1, 2)["base"]
    assert (
        "base from published Dubai ADR calibration"
        in folio(engine.quote(other, DAY, 1, 2), other)["lines"][0]["basis"]
    )


@pytest.mark.parametrize(
    "supplier,expected",
    [(100, "at parity"), (103, "at parity"), (97, "at parity"), (104, "above"), (96, "below")],
)
def test_parity_thresholds(supplier, expected):
    assert parity(supplier, "100")["verdict"] == expected
    assert parity(supplier, None)["verdict"] == "unavailable"


def test_market_service_dates_age_no_key_live_and_parity(tmp_path, market_engine, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    repository = MarketRepository(tmp_path)
    repository.save_live(row(xotelo_observation()))
    repository.save_live(row(serp_observation()))
    service = MarketService(
        market_engine, repository, clock=lambda: datetime.fromisoformat(STAMP) + timedelta(hours=4)
    )
    result = service.check("node/123", DAY, 1, live=True)
    assert result["supplier_quote"]["synthetic"]
    a, b = result["providers"]
    assert a["observation"]["age_hours"] == 4
    assert a["parity"]["verdict"] == "unavailable"
    assert b["parity"]["market_total_aed"] == "510.00"
    assert b["error"]["code"] == "market_key_missing"
    assert all(p["observation"] is None for p in service.check("node/123", DAY, 2)["providers"])
    assert service.summary()["hotels_with_observations"] == 1


def test_snapshot_full_list_refresh_and_calibration(
    tmp_path, market_engine, fake_time, monkeypatch
):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    _, clock, sleep = fake_time
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json=fixture(
                "xotelo/list.json" if request.url.path.endswith("/list") else "xotelo/rates.json"
            ),
        )

    xotelo = Xotelo(tmp_path, httpx.Client(transport=httpx.MockTransport(handler)), clock, sleep)
    result = fetch_snapshot(
        root=tmp_path,
        today=date(2026, 11, 11),
        provider="xotelo",
        catalog=market_engine.catalog,
        xotelo=xotelo,
        calibration_path=tmp_path / "calibration.json",
    )
    assert len(result["observations"]) == 3 and result["manifest"]["searched"] == 4
    assert read_json(tmp_path / "calibration.json")["anchors"]["node/123"]["anchor_aed"] == "403.98"
    assert result["manifest"]["matched_hotels"] == 1
    refreshed = fetch_snapshot(
        root=tmp_path,
        today=date(2026, 11, 12),
        provider="xotelo",
        refresh=1,
        catalog=market_engine.catalog,
        xotelo=xotelo,
        calibration_path=tmp_path / "calibration.json",
    )
    assert refreshed["manifest"]["searched"] == 1
    assert len([r for r in calls if r.url.path.endswith("/list")]) == 1


def test_serp_snapshot_36_queries_one_extra_page_budget(
    tmp_path, market_engine, fake_time, monkeypatch
):
    monkeypatch.setenv("SERPAPI_API_KEY", "FIXTURE_ONLY_SECRET")
    _, clock, _ = fake_time

    def handler(request):
        payload = fixture("serpapi/search.json")
        # Every query claims a third page, but the fetcher never follows it.
        if request.url.params.get("next_page_token"):
            payload["serpapi_pagination"]["next_page_token"] = "IGNORED_PAGE_3"
        return httpx.Response(200, json=payload)

    serpapi = SerpApi(
        httpx.Client(transport=httpx.MockTransport(handler)),
        Budget(tmp_path / "budget.json", clock),
        clock,
    )
    result = fetch_snapshot(
        root=tmp_path,
        today=date(2026, 11, 11),
        provider="serpapi",
        catalog=market_engine.catalog,
        serpapi=serpapi,
        calibration_path=tmp_path / "calibration.json",
    )
    assert len(QUERIES) == 12 and len(stay_dates(date(2026, 11, 11))) == 3
    assert result["manifest"]["searched"] == 72 and serpapi.budget.status()["used"] == 72
    assert all(
        "FIXTURE_ONLY_SECRET" not in path.read_text(encoding="utf-8")
        for path in tmp_path.glob("*.json")
    )


def test_deployed_routes_and_live_default(tmp_path, market_engine, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setenv("RATE_TRUTH_MARKET_DIR", str(tmp_path))
    app = create_app(market_engine)
    with TestClient(app) as client:
        result = client.get("/api/market", params={"hotel_id": "node/123", "checkin": str(DAY)})
        assert result.status_code == 200 and result.json()["live_requested"] is False
        assert client.get("/api/market/summary").json()["observations"] == 0
        assert (
            client.get("/api/market", params={"hotel_id": "node/123", "nights": 31}).status_code
            == 422
        )
        assert client.get("/api/market", params={"hotel_id": "node/999"}).status_code == 404


def test_mcp_market_check_offline(tmp_path, market_engine, monkeypatch):
    import asyncio

    monkeypatch.setenv("RATE_TRUTH_MARKET_DIR", str(tmp_path))
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    gateway = Gateway(market_engine)
    gateway.__dict__["market"] = MarketService(market_engine, MarketRepository(tmp_path))

    async def run():
        async with Client(create_server(gateway), mode="2026-07-28") as client:
            result = await client.call_tool(
                "market_check", {"hotel_id": "node/123", "checkin": str(DAY)}
            )
            assert not result.is_error
            assert all(p["observation"] is None for p in result.structured_content["providers"])

    asyncio.run(run())


def test_http_live_xotelo_fetches_then_uses_cache(tmp_path, market_engine, fake_time, monkeypatch):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    _, clock, sleep = fake_time
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=fixture("xotelo/rates.json"))

    prop = fixture("xotelo/list.json")["result"]["list"][0]
    write_json(
        tmp_path / "matches.json",
        {"node/123": {XOTELO: {"property": prop, "match_score": 1, "distance_m": 0}}},
    )
    monkeypatch.setenv("RATE_TRUTH_MARKET_DIR", str(tmp_path))
    app = create_app(market_engine)
    app.state.market.xotelo = Xotelo(
        tmp_path, httpx.Client(transport=httpx.MockTransport(handler)), clock, sleep
    )
    with TestClient(app) as client:
        for _ in range(2):
            response = client.get(
                "/api/market", params={"hotel_id": "node/123", "checkin": str(DAY), "live": True}
            )
            assert response.status_code == 200
            result = response.json()
            assert result["providers"][0]["observation"]["amount_aed"] == "367.25"
            assert result["providers"][0]["observation"]["fetched_at"] == STAMP
    assert len(calls) == 1
    assert calls[0].url.path == "/api/rates"
    assert calls[0].url.params["hotel_key"] == prop["key"]


def test_live_serpapi_changed_identity_is_rejected(tmp_path, market_engine, fake_time, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "FIXTURE_ONLY_SECRET")
    _, clock, _ = fake_time
    prop = fixture("serpapi/search.json")["properties"][0]
    write_json(
        tmp_path / "matches.json",
        {"node/123": {SERPAPI: {"property": prop, "match_score": 1, "distance_m": 0}}},
    )
    changed = {**prop, "gps_coordinates": {"latitude": 26, "longitude": 56}}
    client = SerpApi(
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=changed))),
        Budget(tmp_path / "budget.json", clock),
        clock,
    )
    service = MarketService(market_engine, MarketRepository(tmp_path), serpapi=client)
    result = service.check("node/123", DAY, live=True)
    assert result["providers"][1]["observation"] is None
    assert result["providers"][1]["error"]["code"] == "market_match_changed"
    assert service.repository.records() == []


def test_snapshot_budget_exhaustion_preserves_first_page(
    tmp_path, market_engine, fake_time, monkeypatch
):
    monkeypatch.setenv("SERPAPI_API_KEY", "FIXTURE_ONLY_SECRET")
    _, clock, _ = fake_time
    write_json(tmp_path / "budget.json", {"month": "2026-11", "used": 219})
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=fixture("serpapi/search.json"))

    client = SerpApi(
        httpx.Client(transport=httpx.MockTransport(handler)),
        Budget(tmp_path / "budget.json", clock),
        clock,
    )
    result = fetch_snapshot(
        root=tmp_path,
        today=date(2026, 11, 11),
        provider="serpapi",
        catalog=market_engine.catalog,
        serpapi=client,
        calibration_path=tmp_path / "calibration.json",
    )
    assert len(calls) == 1 and result["manifest"]["budget"]["used"] == 220
    assert result["errors"][0]["code"] == "market_budget_exhausted"
    assert len(result["observations"]) == 1


def test_parser_unexpected_optional_shapes_do_not_crash():
    prop = fixture("serpapi/search.json")["properties"][0]
    prop.update(rate_per_night=["invalid"], total_rate="invalid", prices={"invalid": True})
    assert parse_property(prop, DAY, DAY + timedelta(days=1), STAMP, "query") is None
    prop["gps_coordinates"] = []
    assert parse_property(prop, DAY, DAY + timedelta(days=1), STAMP, "query") is None


def test_ambiguity_margin_includes_runner_below_threshold(market_engine, monkeypatch):
    hotel = market_engine.catalog.get("node/123")
    alternative = hotel.model_copy(update={"id": "node/456", "name": "Alternative"})
    monkeypatch.setattr(
        "rate_truth.market.matching.token_set_ratio", lambda a, b: 0.84 if b == hotel.name else 0.80
    )
    prop = fixture("xotelo/list.json")["result"]["list"][0]
    assert match_property(prop, [hotel, alternative])["status"] == "ambiguous"


def test_parity_preserves_total_over_rounded_nightly(tmp_path, market_engine):
    detail = fixture("serpapi/detail.json")
    detail["total_rate"]["extracted_after_taxes_fees"] = 1000
    obs = parse_property(detail, DAY, DAY + timedelta(days=3), STAMP, "Dubai")
    assert obs.lowest_all_in_aed == "333.33" and obs.total_all_in_aed == "1000.00"
    repository = MarketRepository(tmp_path)
    repository.save_live(row(obs))
    result = MarketService(market_engine, repository).check("node/123", DAY, 3)
    assert result["providers"][1]["parity"]["market_total_aed"] == "1000.00"

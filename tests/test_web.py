import json
from decimal import Decimal

import jsonschema
import pytest
from fastapi.testclient import TestClient

from rate_truth.agent.replay import SUGGESTIONS
from rate_truth.settings import ROOT
from rate_truth.web.app import RateLimiter, create_app


@pytest.fixture
def web(engine):
    with TestClient(create_app(engine, force_replay=True), base_url="http://127.0.0.1") as client:
        yield client


def check(name, data):
    schema = json.loads((ROOT / f"docs/schemas/{name}.json").read_text())
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        data
    )


@pytest.mark.parametrize(
    "endpoint", ["meta", "hotels", "accuracy", "faults", "feeds", "taxes", "eval"]
)
def test_live_endpoint_matches_exported_schema(web, endpoint):
    response = web.get(f"/api/{endpoint}")
    assert response.status_code == 200, response.text
    check(endpoint, response.json())


def test_hotel_and_quote_contract_and_sum(web, hotel):
    detail = web.get(f"/api/hotels/{hotel.id}")
    assert detail.status_code == 200
    check("hotel", detail.json())
    assert len(detail.json()["availability"]) == 30
    quote = web.get("/api/quote", params={"hotel_id": hotel.id, "checkin": "2026-12-14"})
    assert quote.status_code == 200
    data = quote.json()
    check("quote", data)
    assert sum(Decimal(line["amount"]) for line in data["lines"]) == Decimal(data["total"])
    assert all(line["source_url"].startswith("http") for line in data["lines"])


def parse_events(response):
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.endswith("\n\n")
    events = []
    for frame in response.text.strip().split("\n\n"):
        event_line, data_line = frame.split("\n")
        event = event_line.removeprefix("event: ")
        data = json.loads(data_line.removeprefix("data: "))
        check("stream-error" if event == "error" else event, data)
        events.append((event, data))
    return events


def test_sse_frames_and_confirmed_hold(web, scripted_hold_replay):
    events = parse_events(web.post("/api/ask", json={"message": SUGGESTIONS[2]}))
    assert [e for e, _ in events] == [
        "trace",
        "trace",
        "answer",
        "grounding",
        "hold_request",
        "done",
    ]
    hold_request = next(d for e, d in events if e == "hold_request")
    body = {
        "rate_id": hold_request["rate_id"],
        "hold_token": hold_request["hold_token"],
        "confirm": True,
    }
    assert web.post("/api/holds", json={**body, "confirm": False}).status_code == 422
    held = web.post("/api/holds", json=body)
    assert held.status_code == 201
    check("holds", held.json())
    assert web.post("/api/holds", json=body).status_code == 422


def test_ask_rate_limit_and_retry_after(web):
    for _ in range(8):
        assert web.post("/api/ask", json={"message": "London"}).status_code == 200
    response = web.post("/api/ask", json={"message": "London"})
    assert response.status_code == 429
    check("error", response.json())
    assert 1 <= response.json()["error"]["retry_after_s"] <= 60
    assert response.headers["retry-after"]
    assert web.get("/api/meta").status_code == 200


def test_general_limits_expire_and_separate_ips():
    now = [0]
    limiter = RateLimiter(lambda: now[0])
    assert all(limiter.retry("a") == 0 for _ in range(60))
    assert limiter.retry("a") == 60 and limiter.retry("b") == 0
    now[0] = 60
    assert limiter.retry("a") == 0


def test_feeds_download_security_and_invalid_inputs(web, hotel):
    feeds = web.get("/api/feeds").json()["items"]
    assert len(feeds) == 6 and all(f["valid"] for f in feeds)
    for feed in feeds:
        response = web.get("/api/feeds/" + feed["filename"])
        assert response.status_code == 200
        assert response.content.startswith(b"<?xml")
        assert "attachment" in response.headers["content-disposition"]
    assert web.get("/api/feeds/secret.xml").status_code == 404
    assert web.get("/docs").status_code == 404
    assert web.get("/openapi.json").status_code == 404
    response = web.get("/api/hotels", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert "default-src 'none'" in response.headers["content-security-policy"]
    for field, value, code in [
        ("nights", 31, "nights_out_of_range"),
        ("guests", 9, "guests_out_of_range"),
        ("checkin", "2000-01-01", "date_out_of_range"),
    ]:
        response = web.get(
            "/api/quote", params={"hotel_id": hotel.id, "checkin": "2026-12-14", field: value}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
        assert response.json()["error"]["field"] == field


def test_mcp_list_tools_over_mounted_http(web):
    response = web.post(
        "/mcp/",
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28",
            "mcp-method": "tools/list",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
    )
    assert response.status_code == 200, response.text
    assert {t["name"] for t in response.json()["result"]["tools"]} >= {"get_rates", "hold_offer"}


def test_market_endpoints_remain_available(web, hotel):
    summary = web.get("/api/market/summary")
    assert summary.status_code == 200
    check("market-summary", summary.json())
    response = web.get("/api/market", params={"hotel_id": hotel.id, "live": False})
    assert response.status_code == 200
    check("market", response.json())
    assert response.json()["supplier_quote"]["synthetic"]
    assert all(p["observation"] is None for p in response.json()["providers"])


def test_chunked_body_and_strict_confirmation(web):
    response = web.post(
        "/api/ask",
        content=iter([b"x" * 40000, b"x" * 40000]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    check("error", response.json())
    for value in (1, "true", False):
        assert (
            web.post("/api/holds", json={"rate_id": "rt_test", "confirm": value}).status_code == 422
        )


def test_site_checkbox_metro_filter_is_supported(web):
    assert web.get("/api/hotels?near_metro=true").status_code == 200
    assert web.get("/api/hotels?near_metro=1000").status_code == 200
    assert web.get("/api/hotels?near_metro=nonsense").status_code == 422

import asyncio
import json
import socket
import sys
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

import anyio
import httpx
import pytest
import uvicorn
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from rate_truth.contract import DUBAI
from rate_truth.feeds.property_data import build as build_properties
from rate_truth.mcp_server.server import MAX_MCP_REQUEST_BYTES, create_server
from rate_truth.mcp_server.service import Gateway
from rate_truth.supplier.catalog import Catalog
from rate_truth.supplier.models import dubai_today

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def gateway(engine):
    return Gateway(engine)


@pytest.fixture
async def mcp_client(gateway):
    async with Client(create_server(gateway), mode="2026-07-28") as client:
        yield client


def payload(result):
    assert not result.is_error, result.model_dump_json()
    return result.structured_content


def error(result, code=None):
    assert result.is_error, result.model_dump_json()
    body = result.structured_content
    assert set(body) == {"error"}
    assert {"code", "message"} <= set(body["error"]) <= {"code", "message", "field", "rule"}
    assert "Traceback" not in result.model_dump_json()
    if code:
        assert body["error"]["code"] == code
    return body


def stay(hotel):
    return {"hotel_id": hotel.id, "checkin": dubai_today().isoformat(), "nights": 3}


async def test_every_tool_happy_path_resources_and_prompts(mcp_client, hotel):
    tools = await mcp_client.list_tools()
    expected = {
        "search_hotels",
        "get_rates",
        "check_availability",
        "recommend_hotels",
        "compare_hotels",
        "hold_offer",
        "market_check",
        "build_hotel_list_feed",
        "build_ari_messages",
        "validate_feed",
        "run_price_accuracy_audit",
        "explain_mismatch",
        "tax_rules_at",
    }
    assert {t.name for t in tools.tools} == expected
    assert all(t.input_schema["type"] == "object" for t in tools.tools)
    searched = payload(await mcp_client.call_tool("search_hotels", {"limit": 1}))
    assert searched["total"] == 1 and searched["items"][0]["from_folio"]["rate_id"]
    offer = payload(await mcp_client.call_tool("get_rates", stay(hotel)))
    assert offer["folio"]["lines"][0]["label"].startswith("Room rate ")
    assert offer["folio"]["computed_at"].endswith("+04:00")
    availability = payload(await mcp_client.call_tool("check_availability", stay(hotel)))
    assert len(availability["nights"]) == 3 and availability["folio"]["rate_id"]
    recommended = payload(
        await mcp_client.call_tool(
            "recommend_hotels", {"query": "SYNTHETIC TEST HOTEL", "checkin": str(dubai_today())}
        )
    )
    assert recommended["method"] == "bm25" and recommended["items"]
    assert all(f["source"] for f in recommended["items"][0]["card"]["facts"])
    compared = payload(
        await mcp_client.call_tool(
            "compare_hotels", {"hotel_ids": [hotel.id], "checkin": str(dubai_today())}
        )
    )
    assert len(compared["folios"]) == 1
    held = payload(
        await mcp_client.call_tool(
            "hold_offer",
            {
                "rate_id": offer["folio"]["rate_id"],
                "hold_token": offer["hold_token"],
                "confirm": True,
            },
        )
    )
    assert held["mock"] and held["folio"] == offer["folio"]
    built = payload(await mcp_client.call_tool("build_hotel_list_feed", {"hotel_ids": [hotel.id]}))
    assert len(built["items"]) == 2
    assert all(f["valid"] for f in built["items"])
    ari = payload(await mcp_client.call_tool("build_ari_messages", stay(hotel)))
    assert {f["kind"] for f in ari["items"]} == {"transaction", "ari_rate", "ari_avail", "ari_inv"}
    assert all(f["valid"] for f in ari["items"])
    validated = payload(
        await mcp_client.call_tool(
            "validate_feed", {"xml": built["items"][0]["xml"], "kind": "hotel_list"}
        )
    )
    assert validated["valid"] and validated["check"] == "xsd"
    audit = payload(await mcp_client.call_tool("run_price_accuracy_audit", {"n": 1}))
    assert audit["score"] == 1
    sample = payload(
        await mcp_client.call_tool(
            "explain_mismatch", {"sample_id": audit["samples"][0]["id"], "n": 1}
        )
    )
    assert sample["match"]
    rules = payload(await mcp_client.call_tool("tax_rules_at", {"day": "2026-05-12"}))
    assert rules["relief"] and rules["rules"]["municipality"]["rate"] == "0.07"
    for uri in ("hotel://" + quote(hotel.id, safe=""), "feed://latest", "taxes://dubai"):
        resource = await mcp_client.read_resource(uri)
        assert json.loads(resource.contents[0].text)
    prompts = await mcp_client.list_prompts()
    assert {p.name for p in prompts.prompts} == {"plan-a-stay", "daily-accuracy-check"}
    for name in ("plan-a-stay", "daily-accuracy-check"):
        prompt = await mcp_client.get_prompt(name)
        assert "untrusted data" in prompt.messages[0].content.text
        assert hotel.name not in prompt.messages[0].content.text


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("search_hotels", {"limit": 0}),
        ("get_rates", {"hotel_id": "node/123", "checkin": "2000-01-01"}),
        ("check_availability", {"hotel_id": "node/123", "checkin": "2026-12-14", "nights": 31}),
        ("recommend_hotels", {"query": "x", "checkin": "2026-12-14", "limit": 11}),
        ("compare_hotels", {"hotel_ids": [], "checkin": "2026-12-14"}),
        ("hold_offer", {"rate_id": "bad", "hold_token": "x", "confirm": True}),
        ("build_hotel_list_feed", {"hotel_ids": []}),
        ("build_ari_messages", {"hotel_id": "node/123", "checkin": "2026-12-14", "guests": 9}),
        ("validate_feed", {"xml": "", "kind": "hotel_list"}),
        ("run_price_accuracy_audit", {"n": 101}),
        ("explain_mismatch", {"sample_id": "bad"}),
        ("tax_rules_at", {"day": "2099-01-01"}),
    ],
)
async def test_every_tool_bounds_structured_errors(mcp_client, name, args):
    expected = "invalid_input"
    if name == "tax_rules_at":
        expected = "out_of_model_period"
    elif "nights" in args:
        expected = "nights_out_of_range"
    elif "guests" in args:
        expected = "guests_out_of_range"
    elif name == "get_rates":
        expected = "date_out_of_range"
    error(await mcp_client.call_tool(name, args), expected)


@pytest.mark.parametrize("name", ["get_rates", "check_availability", "build_ari_messages"])
async def test_unknown_single_hotel(mcp_client, name):
    error(
        await mcp_client.call_tool(
            name, {"hotel_id": "way/9999999999", "checkin": str(dubai_today())}
        ),
        "unknown_hotel",
    )


@pytest.mark.parametrize("name", ["compare_hotels", "build_hotel_list_feed"])
async def test_unknown_hotel_lists(mcp_client, name):
    args = {"hotel_ids": ["way/9999999999"]}
    if name == "compare_hotels":
        args["checkin"] = str(dubai_today())
    error(await mcp_client.call_tool(name, args), "unknown_hotel")


async def test_unknown_tool_fault_sample_and_xml(mcp_client):
    error(await mcp_client.call_tool("not_a_tool", {}), "unknown_tool")
    error(await mcp_client.call_tool("search_hotels", {"unexpected": 1}), "invalid_input")
    error(
        await mcp_client.call_tool("run_price_accuracy_audit", {"faults": ["bogus"]}),
        "unknown_fault",
    )
    error(
        await mcp_client.call_tool("explain_mismatch", {"sample_id": "sample-0-999", "n": 1}),
        "unknown_sample",
    )
    invalid = payload(
        await mcp_client.call_tool("validate_feed", {"xml": "<wrong/>", "kind": "transaction"})
    )
    assert not invalid["valid"] and invalid["errors"]
    resource = await mcp_client.read_resource("hotel://way%2F9999999999")
    assert json.loads(resource.contents[0].text)["error"]["code"] == "unknown_hotel"


async def test_token_confirmation_binding_expiry_and_single_use(mcp_client, gateway, hotel):
    now = [datetime(2026, 11, 11, 12, tzinfo=DUBAI)]
    gateway.clock = lambda: now[0]
    offer = payload(await mcp_client.call_tool("get_rates", stay(hotel)))
    args = {
        "rate_id": offer["folio"]["rate_id"],
        "hold_token": offer["hold_token"],
        "confirm": True,
    }
    for value in (False, "true", 1, None):
        error(await mcp_client.call_tool("hold_offer", {**args, "confirm": value}))
    error(
        await mcp_client.call_tool("hold_offer", {**args, "rate_id": "rt_" + "0" * 64}),
        "rate_token_mismatch",
    )
    error(
        await mcp_client.call_tool("hold_offer", {**args, "hold_token": "x" * 43}),
        "invalid_hold_token",
    )
    before = gateway.engine.inventory.availability(hotel, dubai_today(), 3)["available"]
    results = await asyncio.gather(*(mcp_client.call_tool("hold_offer", args) for _ in range(2)))
    assert sum(not r.is_error for r in results) == 1
    assert gateway.engine.inventory.availability(hotel, dubai_today(), 3)["available"] == before - 1
    expired = payload(await mcp_client.call_tool("get_rates", stay(hotel)))
    now[0] += timedelta(minutes=15)
    error(
        await mcp_client.call_tool("hold_offer", {**args, "hold_token": expired["hold_token"]}),
        "invalid_hold_token",
    )


async def test_real_stateless_streamable_http(gateway, hotel):
    mcp = create_server(gateway)
    app = mcp.streamable_http_app(
        stateless_http=True, json_response=True, max_request_body_size=MAX_MCP_REQUEST_BYTES
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        with anyio.fail_after(10):
            while not server.started:
                assert thread.is_alive()
                await anyio.sleep(0.01)
        url = f"http://127.0.0.1:{port}/mcp"
        async with Client(url, mode="2026-07-28") as client:
            assert client.protocol_version == "2026-07-28"
            offer = payload(await client.call_tool("get_rates", stay(hotel)))
            # A full real-snapshot property feed exceeds 1 MB. It must fit the public validator.
            xml = build_properties(Catalog().hotels.values()).xml.decode()
            checked = payload(
                await client.call_tool("validate_feed", {"xml": xml, "kind": "property_data"})
            )
            assert checked["valid"] and checked["check"] == "xsd"
        # A second independent HTTP client can use the capability token; no MCP session required.
        async with Client(url, mode="2026-07-28") as client:
            held = payload(
                await client.call_tool(
                    "hold_offer",
                    {
                        "rate_id": offer["folio"]["rate_id"],
                        "hold_token": offer["hold_token"],
                        "confirm": True,
                    },
                )
            )
            assert held["mock"]
            error(
                await client.call_tool("get_rates", {**stay(hotel), "nights": 0}),
                "nights_out_of_range",
            )
        async with httpx.AsyncClient() as http:
            response = await http.post(
                url,
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
                headers={
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Method": "tools/list",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert response.status_code == 200, response.text
            assert "mcp-session-id" not in response.headers
            assert len(response.json()["result"]["tools"]) == 13
    finally:
        server.should_exit = True
        await anyio.to_thread.run_sync(lambda: thread.join(5))
        sock.close()
        assert not thread.is_alive()


async def test_stdio_entry_point():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "rate_truth.mcp_server.server"]
    )
    async with Client(params, mode="2026-07-28") as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 13
        result = payload(await client.call_tool("tax_rules_at", {"day": "2026-05-12"}))
        assert result["relief"]

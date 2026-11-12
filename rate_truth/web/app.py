"""Same-origin web contract and the stateless MCP server used by the agent."""

import json
import math
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from threading import Lock
from typing import Annotated

from fastapi import Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from starlette.routing import Route

from rate_truth.accuracy.faults import FAULT_IDS, FAULTS
from rate_truth.accuracy.sampler import audit
from rate_truth.agent.loop import Agent
from rate_truth.contract import folio
from rate_truth.errors import validation_detail
from rate_truth.feeds.validate import XSD_DIR
from rate_truth.mcp_server.server import MAX_MCP_REQUEST_BYTES, create_server
from rate_truth.mcp_server.service import Gateway, GatewayError
from rate_truth.settings import DATA, ROOT
from rate_truth.supplier.booking_api import create_app as supplier_app
from rate_truth.supplier.models import StayRequest, dubai_today
from rate_truth.web import models as m
from rate_truth.web.body_limit import BodyLimit
from rate_truth.web.client_ip import client_ip
from rate_truth.web.mcp_transport import SecureMCP


class RateLimiter:
    """Sliding-minute per-IP buckets, local to this instance."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.buckets, self.lock = clock, defaultdict(deque), Lock()

    def retry(self, ip, ask=False):
        now = self.clock()
        with self.lock:
            for key in list(self.buckets):
                if not self.buckets[key] or self.buckets[key][-1] <= now - 60:
                    del self.buckets[key]
            key = (ip, ask)
            bucket = self.buckets[key]
            while bucket and bucket[0] <= now - 60:
                bucket.popleft()
            if len(bucket) >= (8 if ask else 60):
                return max(1, math.ceil(bucket[0] + 60 - now))
            if len(self.buckets) > 10000:
                return 60
            bucket.append(now)
        return 0


def eval_results():
    path = ROOT / "eval/results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"run_at": None}


def taxes_output(taxes):
    today, rules = dubai_today(), []
    for rule in [*taxes.data["rules"], *taxes.data["relief"]]:
        relief = "affects" in rule
        rules.append(
            {
                "id": rule["id"],
                "label": rule.get("kind", rule["id"]).replace("_", " "),
                "kind": "per_room_night" if rule.get("kind") == "tourism_dirham" else "percent",
                "value": str(Decimal(rule["rate"]) * 100)
                if "rate" in rule
                else "100"
                if relief
                else "; ".join(
                    f"{k} star: {v['amount']}" for k, v in rule["hotel_categories"].items()
                ),
                "base": rule.get("base", "Collected proceeds remitted; guest charges unchanged"),
                "applies_from": rule["effective_from"],
                "applies_to": rule.get("effective_to"),
                "status": "ended"
                if rule.get("effective_to") and date.fromisoformat(rule["effective_to"]) < today
                else "uncertain"
                if relief
                else "in_force",
                "source_url": rule["source"],
                "accessed": rule["accessed"],
                "confidence": rule["confidence"],
                "note": rule.get("note", "")
                + " "
                + rule.get("effect", "")
                + " "
                + rule.get("traveller_charge_effect", ""),
            }
        )
    expanded = []
    for rule in rules:
        if rule["kind"] == "per_room_night":
            for category, item in taxes.data["rules"][-1]["hotel_categories"].items():
                expanded.append(
                    {
                        **rule,
                        "id": rule["id"] + "_" + category,
                        "label": f"Tourism Dirham ({category} star)",
                        "value": item["amount"],
                    }
                )
        else:
            expanded.append(rule)
    return {
        "rules": expanded,
        "scenarios": [
            {
                "id": r["id"],
                "label": r["id"].replace("_", " "),
                "description": r.get("effect", "") + " " + r.get("traveller_charge_effect", ""),
            }
            for r in taxes.data["relief"]
        ],
    }


def create_app(engine=None, *, agent=None, force_replay=None):
    gateway = Gateway(engine)
    server = create_server(gateway)
    mcp_app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=MAX_MCP_REQUEST_BYTES,
        streamable_http_path="/",
        # SecureMCP uses the SDK validator with configured subdomain support.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    app = supplier_app(gateway.engine)
    app.add_middleware(BodyLimit)
    app.router.routes[:] = [
        r
        for r in app.router.routes
        if getattr(r, "path", "")
        not in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
    ]
    gateway.__dict__["market"] = app.state.market
    agent = agent or Agent(
        server,
        gateway,
        force_replay=(
            os.environ.get("RATE_TRUTH_LLM_MODE") == "replay"
            if force_replay is None
            else force_replay
        ),
    )
    app.state.gateway, app.state.agent = gateway, agent
    app.state.limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def public_limits(request, call_next):
        ip = client_ip(request)
        retry = app.state.limiter.retry(ip, request.url.path == "/api/ask")
        if retry:
            response = JSONResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": f"Please try again in {retry} seconds.",
                        "retry_after_s": retry,
                    }
                },
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        elif (
            request.headers.get("content-length", "").isdigit()
            and int(request.headers["content-length"]) > MAX_MCP_REQUEST_BYTES
        ):
            response = JSONResponse(
                {
                    "error": {
                        "code": "invalid_input",
                        "message": "request body exceeds the byte limit",
                    }
                },
                status_code=413,
            )
        else:
            response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            }
        )
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error(_request, exc):
        status = 404 if exc.code == "unknown_hotel" else 422
        field = "hotel_id" if exc.code == "unknown_hotel" else "hold_token"
        return JSONResponse(
            {"error": {"code": exc.code, "message": str(exc), "field": field, "rule": str(exc)}},
            status_code=status,
        )

    @app.exception_handler(ValidationError)
    async def validation_error(_request, exc):
        return JSONResponse({"error": validation_detail(exc)}, status_code=422)

    @app.get("/api/meta", response_model=m.Meta)
    def meta(request: Request):
        osm = json.loads((DATA / "osm/hotels.json").read_text(encoding="utf-8"))
        return {
            "hotels": len(gateway.engine.catalog.hotels),
            "pois": len(gateway.cards.pois),
            "osm_fetched_at": osm["fetched_at"],
            "tax_rules_version": gateway.engine.taxes.fingerprint,
            "xsd_fetched_at": (XSD_DIR / "FETCHED_AT").read_text().strip(),
            "eval_run_at": eval_results()["run_at"],
            "llm_mode": agent.mode,
            "retrieval_mode": gateway.index.mode,
            "mcp_url": str(request.base_url).rstrip("/") + "/mcp",
        }

    @app.get("/api/hotels", response_model=m.Hotels)
    def hotels(
        q: Annotated[str, Query(max_length=200)] = "",
        area: str | None = None,
        stars: Annotated[int | None, Query(ge=1, le=5)] = None,
        near_metro: Annotated[str | None, Query(max_length=5)] = None,
        max_total: Annotated[Decimal | None, Query(ge=0, le=1000000)] = None,
        checkin: date | None = None,
        nights: Annotated[int, Query(ge=1, le=30)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    ):
        # The existing site's checkbox serializes true/false. Numeric callers use metres.
        metres = None
        if near_metro not in (None, "false"):
            if near_metro == "true":
                metres = 1000
            elif near_metro.isdigit() and 0 <= int(near_metro) <= 10000:
                metres = int(near_metro)
            else:
                raise GatewayError(
                    "invalid_input", "near_metro must be true, false or 0-10000 metres"
                )
        return gateway.search(
            display=True,
            q=q,
            area=area,
            stars=stars,
            near_metro=metres,
            max_total=max_total,
            checkin=checkin,
            nights=nights,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/hotels/{hotel_id:path}", response_model=m.HotelDetail)
    def hotel(hotel_id: str):
        h = gateway.get_hotel(hotel_id)
        today = dubai_today()
        availability = []
        for offset in range(30):
            day = today + timedelta(days=offset)
            stock = gateway.engine.inventory.availability(h, day, 1, "standard")
            _, f = gateway.quote(gateway.stay(h.id, day))
            availability.append(
                {
                    "date": day,
                    "rooms_left": stock["available"],
                    "from_total": f["total"] if stock["available"] else None,
                }
            )
        return {
            **gateway.cards.records[h.id],
            "tonight": gateway.quote(gateway.stay(h.id, today))[1],
            "availability": availability,
        }

    @app.get("/api/quote", response_model=m.Folio)
    def quote(params: Annotated[StayRequest, Query()]):
        h = gateway.get_hotel(params.hotel_id)
        q = gateway.engine.quote(
            h,
            params.checkin,
            params.nights,
            params.guests,
            params.plan,
            params.room_type,
            as_of=params.as_of,
        )
        return folio(q, h)

    @app.post("/api/ask")
    async def ask(body: m.AskRequest):
        async def events():
            async for event, data in agent.stream(
                body.message, [h.model_dump() for h in body.history]
            ):
                validated = (
                    m.EVENTS[event].model_validate(data).model_dump(mode="json", exclude_unset=True)
                )
                yield f"event: {event}\ndata: {json.dumps(validated, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
        )

    @app.post("/api/holds", response_model=m.Hold, status_code=201)
    def hold(body: m.HoldBody, request: Request):
        return gateway.hold(
            body.rate_id,
            body.hold_token,
            body.confirm,
            client_id=client_ip(request),
        )

    @app.get("/api/accuracy", response_model=m.Accuracy)
    def accuracy(
        faults: str = "",
        seed: Annotated[int, Query(ge=0, le=2147483647)] = 2026,
        n: Annotated[int, Query(ge=1, le=100)] = 30,
    ):
        selected = list(dict.fromkeys(faults.split(","))) if faults else []
        if set(selected) - FAULT_IDS:
            raise GatewayError("unknown_fault", "faults must use the published fault ids")
        return audit(gateway.engine, faults=selected, seed=seed, n=n)

    @app.get("/api/faults", response_model=m.Faults)
    def faults():
        return FAULTS

    def build_feeds():
        gateway.build_hotel_list()
        identifier = next(iter(gateway.engine.catalog.hotels))
        gateway.build_ari(gateway.stay(identifier, dubai_today()))

    @app.get("/api/feeds", response_model=m.Feeds)
    def feeds():
        build_feeds()
        return {"items": [f.output() for f in gateway.latest.values()]}

    @app.get("/api/feeds/{filename}")
    def feed(filename: str):
        if filename not in {
            f"{kind}.xml"
            for kind in (
                "hotel_list",
                "property_data",
                "transaction",
                "ari_rate",
                "ari_avail",
                "ari_inv",
            )
        }:
            return JSONResponse({"error": {"code": "unknown_feed", "message": "unknown feed"}}, 404)
        if filename not in gateway.latest:
            build_feeds()
        return Response(
            gateway.latest[filename].xml,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/taxes", response_model=m.Taxes)
    def taxes():
        return taxes_output(gateway.engine.taxes)

    @app.get("/api/eval", response_model=m.Eval)
    def evaluation():
        return eval_results()

    @app.get("/docs/supplier-model.md", include_in_schema=False)
    def model_document():
        return Response(
            (ROOT / "docs/supplier-model.md").read_text(encoding="utf-8"), media_type="text/plain"
        )

    secured_mcp = SecureMCP(mcp_app)
    # Exact routes avoid Starlette Mount's /mcp -> /mcp/ redirect.
    app.router.routes.extend(
        [
            Route("/mcp", secured_mcp, methods=["GET", "POST", "DELETE"]),
            Route("/mcp/", secured_mcp, methods=["GET", "POST", "DELETE"]),
        ]
    )
    return app


app = create_app()

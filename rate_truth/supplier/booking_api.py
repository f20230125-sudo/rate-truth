"""JSON landing-page supplier with bounded inputs and mock holds only."""

import json
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from rate_truth.errors import validation_detail
from rate_truth.geo import UNKNOWN_STARS
from rate_truth.settings import DISCLOSURE, ORIGIN
from rate_truth.supplier.inventory import HoldLimit, SoldOut
from rate_truth.supplier.models import HoldRequest, HotelID, HotelListRequest, Plan, StayRequest
from rate_truth.supplier.rates import RateEngine
from rate_truth.supplier.taxes import OutOfModelPeriod
from rate_truth.web.client_ip import client_ip


def create_app(engine: RateEngine | None = None) -> FastAPI:
    engine = engine or RateEngine()
    development = os.environ.get("RATE_TRUTH_ENV") == "development"
    app = FastAPI(
        title="Rate Truth — SYNTHETIC supplier",
        description=DISCLOSURE,
        docs_url="/docs" if development else None,
        redoc_url="/redoc" if development else None,
        openapi_url="/openapi.json" if development else None,
    )
    app.state.engine = engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    def error(code: str, message: str, status: int):
        return JSONResponse(
            {
                "error": {"code": code, "message": message},
                "synthetic": True,
                "disclosure": DISCLOSURE,
            },
            status_code=status,
        )

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.headers.get("origin") not in (None, ORIGIN):
            return error("origin_not_allowed", "origin is not allowed", 403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Rate-Truth"] = "synthetic"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        return JSONResponse({"error": validation_detail(_exc)}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return error("http_error", "request is not supported", exc.status_code)

    @app.exception_handler(ValueError)
    async def invalid_value(_request, exc):
        if isinstance(exc, HoldLimit):
            return error(exc.code, str(exc), exc.status)
        if isinstance(exc, OutOfModelPeriod):
            return error(exc.code, str(exc), 422)
        if str(exc) == "unknown hotel id":
            return error("unknown_hotel", "unknown hotel id", 404)
        if isinstance(exc, SoldOut):
            return error("sold_out", str(exc), 409)
        return error("invalid_input", "invalid request parameters", 422)

    @app.exception_handler(FileNotFoundError)
    async def missing_data(_request, _exc):
        return error(
            "data_unavailable", "OSM snapshot is unavailable; run scripts/fetch_osm.py", 503
        )

    @app.exception_handler(Exception)
    async def unexpected(_request, _exc):
        return error("internal_error", "supplier could not process this request", 500)

    def stay_request(params: Annotated[StayRequest, Query()]) -> StayRequest:
        # Current FastAPI validates query models, including cross-field validators.
        return params

    @app.get("/hotels")
    def hotels(params: Annotated[HotelListRequest, Query()]):
        records = list(engine.catalog.hotels.values())
        if params.name:
            records = [h for h in records if params.name.casefold() in h.name.casefold()]
        return {
            "total": len(records),
            "hotels": [
                h.model_dump() for h in records[params.offset : params.offset + params.limit]
            ],
            "synthetic": True,
            "disclosure": DISCLOSURE,
        }

    @app.get("/hotels/{hotel_id:path}")
    def hotel(hotel_id: HotelID):
        return {
            "hotel": engine.catalog.get(hotel_id).model_dump(),
            "room_types": engine.room_types(),
            "plans": [p.value for p in Plan],
            "synthetic": True,
            "disclosure": DISCLOSURE,
        }

    @app.get("/quote")
    def landing_price(stay: Annotated[StayRequest, Depends(stay_request)]):
        return engine.quote(
            engine.catalog.get(stay.hotel_id),
            stay.checkin,
            stay.nights,
            stay.guests,
            stay.plan,
            stay.room_type,
            as_of=stay.as_of,
        )

    @app.get("/availability")
    def availability(stay: Annotated[StayRequest, Depends(stay_request)]):
        hotel = engine.catalog.get(stay.hotel_id)
        result = engine.inventory.availability(
            engine.catalog.get(stay.hotel_id), stay.checkin, stay.nights, stay.room_type
        )
        return {
            **result,
            "synthetic": True,
            "disclosure": DISCLOSURE,
            "stars_description": UNKNOWN_STARS if hotel.stars is None else None,
        }

    @app.post("/holds", status_code=201)
    async def hold(request: Request):
        client_id = client_ip(request)
        engine.inventory.throttle(client_id)
        # Bound streamed/chunked bodies too; never allocate an unbounded request body.
        body_bytes = bytearray()
        async for chunk in request.stream():
            if len(body_bytes) + len(chunk) > 8192:
                return error("invalid_input", "hold body is too large", 413)
            body_bytes.extend(chunk)
        try:
            body = json.loads(body_bytes)
            if not isinstance(body, dict) or body.get("confirm") is not True:
                return error(
                    "confirmation_required", "confirm=true is required for a mock hold", 422
                )
            stay = HoldRequest.model_validate(body)
        except (ValidationError, ValueError):
            return error("invalid_input", "invalid hold parameters", 422)
        hotel = engine.catalog.get(stay.hotel_id)
        price = engine.quote(
            hotel, stay.checkin, stay.nights, stay.guests, stay.plan, stay.room_type
        )
        result = engine.inventory.hold(hotel, price, confirm=stay.confirm, client_id=client_id)
        # FastAPI converts dates; Decimal amounts already are canonical strings in the quote.
        return {**result, "synthetic": True, "disclosure": DISCLOSURE}

    from rate_truth.market.routes import install_market_routes

    install_market_routes(app, engine)

    return app


app = create_app()

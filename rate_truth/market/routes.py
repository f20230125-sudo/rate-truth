"""The same market HTTP routes are mounted in the supplier and deployed web API."""

import time
from collections import defaultdict, deque
from datetime import date
from threading import Lock
from typing import Annotated

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from rate_truth.market.base import MarketError
from rate_truth.market.service import MarketService
from rate_truth.supplier.models import HotelID, dubai_today
from rate_truth.web.client_ip import client_ip


def install_market_routes(app, engine, service=None):
    market = service or MarketService(engine)
    app.state.market = market
    live_buckets, live_lock = defaultdict(deque), Lock()

    @app.exception_handler(MarketError)
    async def market_error(_request, exc):
        status = 429 if exc.code == "market_budget_exhausted" else 503
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=status)

    @app.get("/api/market/summary")
    def summary():
        return market.summary()

    @app.get("/api/market")
    def check(
        request: Request,
        hotel_id: HotelID,
        checkin: date | None = None,
        nights: Annotated[int, Query(ge=1, le=30)] = 1,
        live: bool = False,
    ):
        if live:
            now = time.monotonic()
            with live_lock:
                for key in list(live_buckets):
                    if not live_buckets[key] or live_buckets[key][-1] <= now - 60:
                        del live_buckets[key]
                bucket = live_buckets[client_ip(request)]
                while bucket and bucket[0] <= now - 60:
                    bucket.popleft()
                if len(bucket) >= 6 or len(live_buckets) > 10000:
                    return JSONResponse(
                        {
                            "error": {
                                "code": "rate_limited",
                                "message": "Live market checks allow 6 per minute",
                            }
                        },
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
                bucket.append(now)
        return market.check(hotel_id, checkin or dubai_today(), nights, live)

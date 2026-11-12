"""Market check shared by MCP and HTTP. Only compare explicitly tax-inclusive prices."""

from datetime import datetime, timedelta
from decimal import Decimal

from rate_truth.market.base import SERPAPI, XOTELO, MarketError, amount
from rate_truth.market.budget import Budget
from rate_truth.market.matching import match_property
from rate_truth.market.repository import MarketRepository
from rate_truth.market.serpapi import SerpApi
from rate_truth.market.storage import utcnow
from rate_truth.market.xotelo import Xotelo
from rate_truth.supplier.models import StayRequest, money


def parity(supplier_total, market_total):
    market = amount(market_total)
    if market is None or market <= 0:
        return {"verdict": "unavailable", "reason": "market all-in price not stated"}
    delta = (Decimal(supplier_total) - market) / market * 100
    return {
        "verdict": "at parity" if abs(delta) <= 3 else "above" if delta > 0 else "below",
        "difference_percent": str(money(delta)),
        "market_total_aed": str(money(market)),
        "scope": "price comparison only; room, cancellation and meal terms may differ",
    }


class MarketService:
    def __init__(self, engine, repository=None, xotelo=None, serpapi=None, clock=utcnow):
        self.engine = engine
        self.repository = repository or MarketRepository()
        self.xotelo = xotelo or Xotelo(root=self.repository.root)
        self.serpapi = serpapi or SerpApi(budget=Budget(self.repository.root / "budget.json"))
        self.clock = clock

    def check(self, hotel_id, checkin, nights=1, live=False):
        hotel = self.engine.catalog.get(hotel_id)
        stay = StayRequest(hotel_id=hotel_id, checkin=checkin, nights=nights)
        checkout = checkin + timedelta(days=stay.nights)
        quote = self.engine.quote(hotel, checkin, nights, 2)
        matches = self.repository.matches().get(hotel_id, {})
        errors = {}
        if live:
            for provider in (self.xotelo, self.serpapi):
                if provider.label == SERPAPI and not provider.enabled:
                    errors[provider.label] = {
                        "code": "market_key_missing",
                        "message": "SERPAPI_API_KEY is not set",
                    }
                    continue
                entry = matches.get(provider.label)
                if not entry:
                    continue
                try:
                    observed = provider.observe(entry["property"], checkin, checkout)
                    if observed:
                        identity = match_property(
                            {
                                "name": observed.name,
                                "gps_coordinates": {
                                    "latitude": observed.lat,
                                    "longitude": observed.lon,
                                },
                            },
                            self.engine.catalog.hotels.values(),
                        )
                        if identity.get("hotel_id") != hotel_id:
                            raise MarketError("market_match_changed", "live identity did not match")
                        self.repository.save_live(
                            {
                                "hotel_id": hotel_id,
                                "match_score": identity["score"],
                                "distance_m": identity["distance_m"],
                                "observation": observed.output(),
                            }
                        )
                except MarketError as exc:
                    errors[provider.label] = {"code": exc.code, "message": str(exc)}
        records = [r for r in self.repository.records() if r["hotel_id"] == hotel_id]
        outputs = []
        for label in (XOTELO, SERPAPI):
            candidates = [
                r
                for r in records
                if r["observation"]["provider"] == label
                and r["observation"]["checkin"] == checkin.isoformat()
                and r["observation"]["checkout"] == checkout.isoformat()
            ]
            current = max(candidates, key=lambda r: r["observation"]["fetched_at"], default=None)
            result = {
                "provider": label,
                "observation": None,
                "message": "no observation for this hotel and stay",
            }
            if current:
                o = current["observation"]
                age = max(
                    0,
                    (self.clock() - datetime.fromisoformat(o["fetched_at"])).total_seconds() / 3600,
                )
                all_in = amount(o.get("lowest_all_in_aed"))
                total_all_in = amount(o.get("total_all_in_aed"))
                if total_all_in is None and all_in is not None:
                    total_all_in = all_in * nights
                result = {
                    "provider": label,
                    "observation": {
                        **o,
                        "age_hours": round(age, 3),
                        "match_score": current.get("match_score"),
                        "disclosure": "observed price, not a quote",
                    },
                    "parity": parity(quote["total"], total_all_in),
                }
            if label in errors:
                result["error"] = errors[label]
            outputs.append(result)
        return {
            "hotel_id": hotel_id,
            "checkin": checkin.isoformat(),
            "nights": nights,
            "currency": "AED",
            "providers": outputs,
            "supplier_quote": quote,
            "live_requested": live,
            "disclosure": "observed price, not a quote",
        }

    def summary(self):
        records = self.repository.records()
        matches = self.repository.matches()
        return {
            "snapshot_date": max(
                (
                    p.name[9:19]
                    for p in (
                        set(self.repository.root.glob("snapshot-*.json"))
                        | set(self.repository.seed.glob("snapshot-*.json"))
                    )
                ),
                default=None,
            ),
            "observations": len(records),
            "matched_hotels": len(matches),
            "hotels_with_observations": len({r["hotel_id"] for r in records}),
            "providers": [
                {
                    "provider": p,
                    "matched_hotels": sum(p in m for m in matches.values()),
                    "observations": sum(r["observation"]["provider"] == p for r in records),
                    "enabled": p == XOTELO or self.serpapi.enabled,
                }
                for p in (XOTELO, SERPAPI)
            ],
            "budget": self.serpapi.budget.status(),
            "disclosure": "observed price, not a quote",
        }

"""Optional Google Hotels observations through SerpApi only.

Response fields verified against https://serpapi.com/google-hotels-api (2026-11-11).
Do not retain HTTP exceptions: they contain the credential-bearing request URL.
"""

import logging
import os
from decimal import Decimal

import httpx

from rate_truth.market.base import SERPAPI, MarketError, Observation, amount
from rate_truth.market.budget import Budget
from rate_truth.market.storage import scrub, utcnow
from rate_truth.supplier.models import money

API = "https://serpapi.com/search.json"


class CredentialFilter(logging.Filter):
    def filter(self, record):
        record.msg, record.args = scrub(record.getMessage()), ()
        return True


# httpx emits request URLs at INFO. Scrub before any application handlers see them.
logging.getLogger("httpx").addFilter(CredentialFilter())


class SerpApi:
    label = SERPAPI

    def __init__(self, client=None, budget=None, clock=utcnow):
        self.client = client or httpx.Client(timeout=6)
        self.budget = budget or Budget()
        self.clock = clock

    @property
    def enabled(self):
        return bool(os.getenv("SERPAPI_API_KEY"))

    def search(self, query, checkin, checkout, *, property_token=None, next_page_token=None):
        key = os.getenv("SERPAPI_API_KEY")
        if not key:
            raise MarketError("market_key_missing", "SERPAPI_API_KEY is not set")
        params = {
            "engine": "google_hotels",
            "q": query,
            "check_in_date": checkin.isoformat(),
            "check_out_date": checkout.isoformat(),
            "adults": 2,
            "currency": "AED",
            "gl": "ae",
            "hl": "en",
        }
        if property_token:
            params["property_token"] = property_token
        if next_page_token:
            params["next_page_token"] = next_page_token
        self.budget.reserve()  # Failures also consume a reservation. No automatic retries.
        try:
            response = self.client.get(API, params={**params, "api_key": key})
            response.raise_for_status()
            payload = scrub(response.json(), key)
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError("invalid provider response")
        except (httpx.HTTPError, ValueError):
            raise MarketError(
                "market_provider_unavailable", "SerpApi could not return rates"
            ) from None
        return {
            "query": query,
            "params": params,
            "fetched_at": self.clock().isoformat(),
            "response": payload,
        }

    def observe(self, hotel, checkin, checkout):
        saved = self.search(
            hotel["name"],
            checkin,
            checkout,
            property_token=hotel.get("property_token") or hotel.get("key"),
        )
        properties = properties_from(saved["response"])
        # A property token lookup must still be re-matched against OSM by the caller.
        if len(properties) != 1:
            return None
        return parse_property(properties[0], checkin, checkout, saved["fetched_at"], hotel["name"])


def properties_from(payload):
    rows = payload.get("properties")
    if isinstance(rows, list):
        return [p for p in rows if isinstance(p, dict)]
    # Google Hotels can return single-property detail fields at the response root.
    return [payload] if payload.get("name") and payload.get("gps_coordinates") else []


def object_value(value):
    return value if isinstance(value, dict) else {}


def parse_property(prop, checkin, checkout, fetched_at, query):
    geo = object_value(prop.get("gps_coordinates"))
    lat, lon = (
        amount_coordinate(geo.get("latitude"), 90),
        amount_coordinate(geo.get("longitude"), 180),
    )
    if lat is None or lon is None or not isinstance(prop.get("name"), str) or not prop["name"]:
        return None
    nights = (checkout - checkin).days
    if nights < 1:
        return None
    nightly, total = object_value(prop.get("rate_per_night")), object_value(prop.get("total_rate"))

    def nightly_value(key):
        value = amount(nightly.get(key))
        if value is None and (v := amount(total.get(key))) is not None:
            value = v / nights
        return value

    before = nightly_value("extracted_before_taxes_fees")
    after = nightly_value("extracted_after_taxes_fees")
    lowest = nightly_value("extracted_lowest")
    # Retain lowest as observed. Only an explicit after-tax field establishes all-in.
    observed = after if after is not None else lowest if lowest is not None else before
    if observed is None:
        return None
    sources = []
    prices = prop.get("prices")
    for row in prices if isinstance(prices, list) else []:
        if not isinstance(row, dict):
            continue
        rate = row.get("rate_per_night") or {}
        if not isinstance(rate, dict):
            continue
        value = amount(rate.get("extracted_lowest"))
        if value is not None:
            source = row.get("source")
            if isinstance(source, dict):
                source = source.get("name")
            sources.append(
                {
                    "site": str(source or "Unknown source"),
                    "amount": str(money(value)),
                    "currency": "AED",
                    "before_tax": rate.get("extracted_before_taxes_fees"),
                    "after_tax": rate.get("extracted_after_taxes_fees"),
                }
            )
    return Observation(
        provider=SERPAPI,
        hotel_key=str(prop.get("property_token") or prop.get("link") or prop["name"]),
        name=prop["name"],
        lat=lat,
        lon=lon,
        checkin=checkin.isoformat(),
        checkout=checkout.isoformat(),
        currency_original="AED",
        amount_original=str(money(observed)),
        amount_aed=str(money(observed)),
        aed_conversion={"rate": "1", "method": "provider currency AED"},
        taxes_included=True if after is not None else False if observed == before else None,
        per_source=sources,
        fetched_at=fetched_at,
        query=query,
        before_tax_aed=str(money(before)) if before is not None else None,
        lowest_all_in_aed=str(money(after)) if after is not None else None,
        total_all_in_aed=str(money(value))
        if (value := amount(total.get("extracted_after_taxes_fees"))) is not None
        else None,
        tax_label="explicit after-tax price"
        if after is not None
        else "taxes not stated for lowest",
        property_token=prop.get("property_token"),
        link=prop.get("link"),
        hotel_class=prop.get("extracted_hotel_class") or prop.get("hotel_class"),
        evidence=scrub({"rate_per_night": nightly, "total_rate": total}),
    )


def amount_coordinate(value, maximum):
    try:
        val = Decimal(str(value))
        return float(val) if val.is_finite() and abs(val) <= maximum else None
    except (ValueError, ArithmeticError):
        return None

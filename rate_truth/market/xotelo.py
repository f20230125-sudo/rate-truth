"""Keyless TripAdvisor partner rates. No /search or direct Google requests."""

import hashlib
import time
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from rate_truth.market.base import XOTELO, MarketError, Observation, amount
from rate_truth.market.storage import file_lock, market_dir, read_json, utcnow, write_json
from rate_truth.supplier.models import money

API = "https://data.xotelo.com/api/"
USER_AGENT = "rate-truth/0.1 (portfolio project)"
# Central Bank of the UAE official fixed USD peg: USD 1 = AED 3.6725.
# https://www.centralbank.ae/en/forex-eibor/exchange-rates/
# Official USD table: https://www.centralbank.ae/media/w53dpzhe/fx_jul24_en.pdf
USD_AED = Decimal("3.6725")
PEG_SOURCE = "https://www.centralbank.ae/en/forex-eibor/exchange-rates/"


class Xotelo:
    label = XOTELO

    def __init__(self, root=None, client=None, clock=utcnow, sleep=time.sleep):
        self.root = root or market_dir()
        self.client = client or httpx.Client(timeout=6, headers={"User-Agent": USER_AGENT})
        self.clock, self.sleep = clock, sleep

    def request(self, endpoint, params):
        if endpoint not in {"list", "rates"}:
            raise ValueError("unsupported Xotelo endpoint")
        url = API + endpoint + "?" + urlencode(sorted(params.items()))
        cache = self.root / "cache" / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        ttl = 7 * 86400 if endpoint == "list" else 6 * 3600

        def cached():
            saved = read_json(cache)
            if saved:
                age = (self.clock() - datetime.fromisoformat(saved["fetched_at"])).total_seconds()
                if 0 <= age < ttl:
                    return saved
            return None

        # Cache hits must not wait behind unrelated network requests.
        if saved := cached():
            return saved
        # One cross-process lock covers cache recheck, pacing and both attempts.
        with file_lock(self.root / "xotelo.lock", timeout=3):
            if saved := cached():
                return saved
            for attempt in range(2):
                pacing = read_json(self.root / "xotelo-pacing.json", {"last": 0})
                self.sleep(max(0, 1 - (self.clock().timestamp() - pacing["last"])))
                write_json(self.root / "xotelo-pacing.json", {"last": self.clock().timestamp()})
                try:
                    response = self.client.get(url, headers={"User-Agent": USER_AGENT})
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or payload.get("error"):
                        raise ValueError("provider error")
                    if not isinstance(payload.get("result"), dict):
                        raise ValueError("missing result")
                    saved = {
                        "url": url,
                        "fetched_at": self.clock().isoformat(),
                        "response": payload,
                    }
                    write_json(cache, saved)
                    return saved
                except (httpx.HTTPError, ValueError):
                    if attempt == 0:
                        self.sleep(2)
                finally:
                    # Pace from completion, avoiding sub-second start gaps due to disk/I/O time.
                    write_json(self.root / "xotelo-pacing.json", {"last": self.clock().timestamp()})
            raise MarketError("market_provider_unavailable", "Xotelo could not return rates")

    def list_all(self):
        """Fetch every Dubai list page, max 100 items each. No RapidAPI search."""
        pages, offset = [], 0
        while True:
            page = self.request(
                "list",
                {"location_key": "g295424", "offset": offset, "limit": 100, "sort": "best_value"},
            )
            result = page["response"]["result"]
            records, total = result.get("list"), result.get("total_count")
            if not isinstance(records, list) or type(total) is not int or total < 0:
                raise MarketError("market_provider_invalid", "Xotelo list shape is invalid")
            pages.append(page)
            if offset + len(records) >= total:
                return pages
            if not records:
                raise MarketError("market_provider_invalid", "Xotelo list ended before total_count")
            offset += len(records)

    def observe(self, hotel, checkin, checkout):
        if (checkout - checkin).days != 1:
            raise MarketError(
                "market_rate_basis_unknown", "Xotelo multi-night price basis has not been verified"
            )
        saved = self.request(
            "rates",
            {
                "hotel_key": hotel["key"],
                "chk_in": checkin.isoformat(),
                "chk_out": checkout.isoformat(),
                "currency": "USD",
            },
        )
        return parse_rates(saved["response"], hotel, checkin, checkout, saved["fetched_at"])


def parse_rates(payload, hotel, checkin, checkout, fetched_at):
    result = payload.get("result") or {}
    sources = []
    for row in (payload.get("result") or {}).get("rates", []) or []:
        if not isinstance(row, dict) or (price := amount(row.get("rate"))) is None:
            continue
        sources.append(
            {
                "site": str(row.get("name") or row.get("code") or "Unknown source"),
                "amount": str(money(price * USD_AED)),
                "currency": "AED",
                "amount_original": str(price),
                "currency_original": "USD",
                "tax_original": str(tax) if (tax := amount(row.get("tax"))) is not None else None,
            }
        )
    if not sources:
        return None
    lowest = min(sources, key=lambda s: Decimal(s["amount_original"]))
    # Use changed fields returned by the provider, so the caller can recheck identity.
    live_hotel = result.get("hotel") if isinstance(result.get("hotel"), dict) else {}
    identity = {**hotel, **live_hotel}
    for key in ("name", "geo"):
        if key in result:
            identity[key] = result[key]
    geo = identity.get("geo") or {}
    try:
        lat, lon = float(geo["latitude"]), float(geo["longitude"])
    except (KeyError, ValueError, TypeError):
        raise MarketError("market_match_changed", "live identity coordinates are invalid") from None
    if result.get("hotel_key", hotel["key"]) != hotel["key"]:
        raise MarketError("market_match_changed", "live provider key changed")
    # A numeric tax is retained as evidence, but does not establish inclusion semantics.
    return Observation(
        provider=XOTELO,
        hotel_key=hotel["key"],
        name=identity["name"],
        lat=lat,
        lon=lon,
        checkin=checkin.isoformat(),
        checkout=checkout.isoformat(),
        currency_original="USD",
        amount_original=lowest["amount_original"],
        amount_aed=lowest["amount"],
        aed_conversion={
            "rate": str(USD_AED),
            "method": "official UAE fixed USD peg",
            "source": PEG_SOURCE,
        },
        taxes_included=None,
        per_source=sources,
        fetched_at=fetched_at,
        query=hotel["key"],
        tax_label="as shown by the booking site; taxes not stated"
        if all(s["tax_original"] is None for s in sources)
        else "as shown by the booking site; tax amounts supplied, inclusion not stated",
        link=hotel.get("url"),
        evidence={
            "rates": result.get("rates", []),
            "identity_basis": "live_fields"
            if live_hotel or "name" in result or "geo" in result
            else "matched_list_only",
            "rate_basis": "one-night stay"
            if (checkout - checkin).days == 1
            else "unverified multi-night amount",
        },
    )

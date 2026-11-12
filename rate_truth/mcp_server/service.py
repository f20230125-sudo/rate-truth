"""Shared business operations, independent of MCP transport or future web routes."""

import secrets
from datetime import datetime, timedelta
from functools import cached_property
from threading import RLock

from rate_truth.contract import DUBAI, folio
from rate_truth.feeds import ari, hotel_list, property_data, transaction
from rate_truth.hotel_groups import display_order
from rate_truth.mcp_server.capabilities import sign, signing_secret, token_digest, verify
from rate_truth.rag.cards import Cards
from rate_truth.rag.retrieve import Retriever
from rate_truth.supplier.models import StayRequest, dubai_today
from rate_truth.supplier.rates import RateEngine


class GatewayError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Gateway:
    def __init__(self, engine=None, clock=None):
        self.engine = engine or RateEngine()
        self.cards = Cards(self.engine.catalog)
        self.clock = clock or (lambda: datetime.now(DUBAI))
        self._secret = signing_secret()
        self._consumed = {}
        self._lock = RLock()
        self.latest = {}

    @cached_property
    def index(self):
        return Retriever(self.cards.records)

    @cached_property
    def market(self):
        from rate_truth.market.service import MarketService

        return MarketService(self.engine)

    def get_hotel(self, identifier):
        try:
            return self.engine.catalog.get(identifier)
        except ValueError:
            raise GatewayError("unknown_hotel", "unknown hotel id") from None

    def stay(self, hotel_id, checkin, nights=1, guests=2, plan="refundable", room=None):
        self.get_hotel(hotel_id)
        return StayRequest(
            hotel_id=hotel_id,
            checkin=checkin,
            nights=nights,
            guests=guests,
            plan=plan,
            room_type=room,
        )

    def quote(self, stay):
        h = self.get_hotel(stay.hotel_id)
        q = self.engine.quote(h, stay.checkin, stay.nights, stay.guests, stay.plan, stay.room_type)
        return q, folio(q, h)

    def get_rates(self, stay):
        q, f = self.quote(stay)
        expires = self.clock() + timedelta(minutes=15)
        token = sign(
            {
                "v": 1,
                "kind": "offer",
                "rate_id": q["rate_id"],
                "expires": expires.timestamp(),
                "nonce": secrets.token_urlsafe(16),
                "stay": stay.model_dump(mode="json"),
                "computed_at": q["computed_at"],
            },
            self._secret,
        )
        return {"folio": f, "hold_token": token, "hold_token_expires_at": expires.isoformat()}

    def hold(self, rate_id, hold_token, confirm, client_id="mcp-local"):
        self.engine.inventory.throttle(client_id)
        if confirm is not True:
            raise GatewayError("confirmation_required", "confirm=true is required for a mock hold")
        with self._lock:
            now = self.clock().timestamp()
            self._consumed = {k: v for k, v in self._consumed.items() if v > now}
            try:
                offer = verify(hold_token, self._secret)
                if (
                    offer["v"] != 1
                    or offer["kind"] != "offer"
                    or offer["expires"] <= now
                    or token_digest(hold_token) in self._consumed
                ):
                    raise ValueError("invalid capability")
                stay = StayRequest.model_validate(offer["stay"])
            except (ValueError, KeyError, TypeError):
                raise GatewayError(
                    "invalid_hold_token", "hold token is invalid, consumed or expired"
                ) from None
            if not secrets.compare_digest(offer["rate_id"], rate_id):
                raise GatewayError(
                    "rate_token_mismatch", "hold token was issued for a different rate_id"
                )
            q, _ = self.quote(stay)
            if q["rate_id"] != rate_id:
                raise GatewayError(
                    "invalid_hold_token", "quoted rate has changed; request a new offer"
                )
            q["computed_at"] = offer["computed_at"]
            f = folio(q, self.get_hotel(stay.hotel_id))
            result = self.engine.inventory.hold(
                self.get_hotel(q["hotel_id"]), q, confirm=True, client_id=client_id
            )
            self._consumed[token_digest(hold_token)] = offer["expires"]
            receipt = sign(
                {
                    "v": 1,
                    "kind": "mock_receipt",
                    "rate_id": rate_id,
                    "expires": result["expires_at"].timestamp(),
                    "nonce": secrets.token_urlsafe(16),
                },
                self._secret,
            )
        return {
            "hold_id": "mock_" + receipt,
            "expires_at": result["expires_at"].astimezone(DUBAI).isoformat(),
            "folio": f,
            "mock": True,
        }

    def search(
        self,
        *,
        q="",
        area=None,
        stars=None,
        near_metro=None,
        limit=20,
        offset=0,
        checkin=None,
        nights=1,
        guests=2,
        room=None,
        max_total=None,
        display=False,
    ):
        items = []
        checkin = checkin or dubai_today()
        # Validate dates even if no hotel matches the search.
        first = next(iter(self.engine.catalog.hotels), None)
        if first:
            self.stay(first, checkin, nights, guests, room=room)
        seen = set()
        hotels = self.engine.catalog.hotels.values()
        for hotel in sorted(hotels, key=display_order) if display else hotels:
            if not any(
                q.casefold() in name.casefold() for name in (hotel.name, hotel.name_en or "")
            ):
                continue
            if area and hotel.area != area.removeprefix("near "):
                continue
            # Unknown stars never match a requested actual star rating.
            if stars is not None and hotel.stars != stars:
                continue
            record = self.cards.records[hotel.id]
            if near_metro is not None and (
                record["hotel"]["nearest_metro"] is None
                or record["hotel"]["nearest_metro"]["metres"] > near_metro
            ):
                continue
            _, f = self.quote(self.stay(hotel.id, checkin, nights, guests, room=room))
            if max_total is not None:
                from decimal import Decimal

                if Decimal(f["total"]) > max_total:
                    continue
            group_id = record["hotel"]["mapped_osm_ids"][0]
            if display and group_id in seen:
                continue
            seen.add(group_id)
            # Search needs a compact stay total; full nightly detail is available via get_rates.
            bases = [line for line in f["lines"] if line["kind"] == "base"]
            if bases:
                from decimal import Decimal

                f["lines"] = [
                    {
                        **bases[0],
                        "label": f"Room rate ({nights} nights)",
                        "amount": str(sum(Decimal(i["amount"]) for i in bases)),
                    },
                    *[i for i in f["lines"] if i["kind"] != "base"],
                ]
            items.append({**record["hotel"], "from_folio": f})
        return {"total": len(items), "items": items[offset : offset + limit], "synthetic": True}

    def remember(self, feeds):
        with self._lock:
            self.latest.update({f.filename: f for f in feeds})
        return {"items": [f.output() for f in feeds]}

    def published_feeds(self):
        """Reproducible default feed set; never depends on a previous worker's request."""
        hotels = list(self.engine.catalog.hotels.values())
        self.build_hotel_list()
        if hotels:
            self.build_ari(self.stay(hotels[0].id, dubai_today()))
        return {"items": [f.output() for f in self.latest.values()]}

    def build_hotel_list(self, ids=None):
        hotels = (
            [self.get_hotel(i) for i in ids] if ids else list(self.engine.catalog.hotels.values())
        )
        return self.remember([hotel_list.build(hotels), property_data.build(hotels)])

    def build_ari(self, stay):
        return self.remember(
            [transaction.build(self.engine, [stay]), *ari.build(self.engine, stay)]
        )

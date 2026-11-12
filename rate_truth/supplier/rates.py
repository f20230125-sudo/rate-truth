"""Deterministic synthetic quotes with optional, disclosed matched market anchors."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from rate_truth.geo import UNKNOWN_STARS
from rate_truth.settings import DATA, DISCLOSURE, SEED
from rate_truth.supplier.catalog import Catalog
from rate_truth.supplier.inventory import Inventory, stable_int
from rate_truth.supplier.models import CAPACITY, Hotel, Plan, RoomType, StayRequest, money
from rate_truth.supplier.taxes import TaxRules

ENGINE_VERSION = "synthetic-v2-det-2025-calibrated"
BASE_BY_STARS = {1: 520, 2: 540, 3: 560, 4: 590, 5: 620}
AREA_FACTORS = dict(
    zip(
        ("eastern", "western", "central", "northern", "other"),
        map(Decimal, ("0.95", "1.05", "1.03", "0.97", "1")),
        strict=True,
    )
)
SEASON_FACTORS = {"high": Decimal("1.12"), "summer": Decimal("0.88"), "other": Decimal(1)}
WEEKEND_FACTOR = Decimal("1.06")
YIELD_BASE, YIELD_SPREAD = Decimal("0.96"), Decimal("0.08")
PROPERTY_MIN, PROPERTY_STEPS = 95, 11
NONREF_FACTOR = Decimal("0.90")
BREAKFAST_PER_GUEST = 45
LOS_DISCOUNTS = {3: Decimal("0.05"), 7: Decimal("0.10")}
ROOM_FACTOR = {
    RoomType.STANDARD: Decimal("1"),
    RoomType.DELUXE: Decimal("1.3"),
    RoomType.FAMILY: Decimal("1.8"),
}


def area_for(hotel: Hotel) -> tuple[str, Decimal]:
    """Synthetic coordinate bands, not claimed OSM administrative neighbourhoods."""
    if hotel.lon >= 56:
        return "eastern_emirate_band", AREA_FACTORS["eastern"]
    if hotel.lon < 55.17 and hotel.lat > 25.02:
        return "western_coast_band", AREA_FACTORS["western"]
    if 25.16 <= hotel.lat <= 25.23 and 55.24 <= hotel.lon <= 55.32:
        return "central_band", AREA_FACTORS["central"]
    if hotel.lat >= 25.23:
        return "northern_band", AREA_FACTORS["northern"]
    return "other_dubai_band", AREA_FACTORS["other"]


def los_discount(nights: int) -> Decimal:
    return next(
        (LOS_DISCOUNTS[n] for n in sorted(LOS_DISCOUNTS, reverse=True) if nights >= n), Decimal(0)
    )


def factors(inventory, hotel, night, room_type):
    stock = inventory.stock(hotel, night, room_type)
    occupancy = Decimal(stock["baseline_sold"]) / stock["capacity"]
    season = (
        SEASON_FACTORS["high"]
        if night.month in {11, 12, 1, 2, 3}
        else SEASON_FACTORS["summer"]
        if night.month in {6, 7, 8, 9}
        else SEASON_FACTORS["other"]
    )
    weekend = WEEKEND_FACTOR if night.weekday() in {4, 5} else Decimal(1)
    return occupancy, season, weekend, YIELD_BASE + occupancy * YIELD_SPREAD


class RateEngine:
    def __init__(
        self,
        seed: int = SEED,
        catalog: Catalog | None = None,
        inventory: Inventory | None = None,
        taxes: TaxRules | None = None,
        market_calibration: dict | None = None,
    ):
        self.seed = seed
        self.catalog = catalog or Catalog()
        self.inventory = inventory or Inventory(seed)
        if self.inventory.seed != seed:
            raise ValueError("rate and inventory seeds must match")
        self.taxes = taxes or TaxRules()
        if market_calibration is None:
            path = DATA / "calibration_market.json"
            market_calibration = (
                json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            )
        self.market_anchors = market_calibration.get("anchors", {})

    def quote(
        self,
        hotel: Hotel | str,
        checkin: date,
        nights: int,
        guests: int,
        plan: Plan | str = Plan.REFUNDABLE,
        room_type: RoomType | str | None = None,
        *,
        as_of: date | None = None,
    ) -> dict:
        if isinstance(hotel, str):
            hotel = self.catalog.get(hotel)
        request = StayRequest(
            hotel_id=hotel.id,
            checkin=checkin,
            nights=nights,
            guests=guests,
            plan=plan,
            room_type=room_type,
            as_of=as_of,
        )
        return self._quote_stay(hotel, request)

    def quote_nights(self, stay: StayRequest) -> list[dict]:
        """One-night products within a validated stay, including its departure horizon.

        The public check-in bound applies to the parent stay. Dates after day 365
        are reachable only as occupied nights of that validated parent stay.
        """
        stay = StayRequest.model_validate(stay.model_dump())
        hotel = self.catalog.get(stay.hotel_id)
        return [
            self._quote_stay(
                hotel,
                stay.model_copy(
                    update={
                        "checkin": stay.checkin + timedelta(days=index),
                        "nights": 1,
                    }
                ),
            )
            for index in range(stay.nights)
        ]

    def _quote_stay(self, hotel: Hotel, request: StayRequest) -> dict:
        plan, room_type = request.plan, request.room_type
        checkin, nights, guests = request.checkin, request.nights, request.guests
        area, area_factor = area_for(hotel)
        property_factor = (
            Decimal(PROPERTY_MIN + stable_int(self.seed, hotel.id, "price") % PROPERTY_STEPS) / 100
        )
        discount = los_discount(nights)
        plan_factor = NONREF_FACTOR if plan.value.startswith("non_refundable") else Decimal(1)
        breakfast = BREAKFAST_PER_GUEST * guests if plan.value.endswith("breakfast") else 0
        anchor = self.market_anchors.get(hotel.id)
        anchor_scale = Decimal(1)
        calibration = {"basis": "base from published Dubai ADR calibration"}
        if anchor:
            ref = date.fromisoformat(anchor["reference_checkin"])
            ref_nights = anchor.get("reference_nights", 1)
            reference_rates = []
            for offset in range(ref_nights):
                _, season, weekend, yield_factor = factors(
                    self.inventory, hotel, ref + timedelta(days=offset), RoomType.STANDARD
                )
                reference_rates.append(
                    Decimal(BASE_BY_STARS[hotel.pricing_stars])
                    * area_factor
                    * property_factor
                    * season
                    * weekend
                    * yield_factor
                    * (1 - los_discount(ref_nights))
                )
            reference = sum(reference_rates) / ref_nights
            anchor_scale = Decimal(anchor["anchor_aed"]) / reference
            calibration = {
                **anchor,
                "basis": f"base anchored to {anchor['provider']} price seen "
                f"{anchor['fetched_at'][:10]}; {anchor['basis']}",
            }
        nightly, line_items = [], []
        base = Decimal(0)
        for index in range(nights):
            night = checkin + timedelta(days=index)
            occupancy, season, weekend, yield_factor = factors(
                self.inventory, hotel, night, room_type
            )
            room = (
                Decimal(BASE_BY_STARS[hotel.pricing_stars])
                * area_factor
                * property_factor
                * ROOM_FACTOR[room_type]
                * season
                * weekend
                * yield_factor
                * anchor_scale
            )
            # Plan and LOS reductions apply to the room; breakfast is an undiscounted add-on.
            room_before_los = room * plan_factor
            net = money(room_before_los * (1 - discount) + breakfast)
            base += net
            nightly.append(
                {
                    "date": night.isoformat(),
                    "base": str(net),
                    "room_before_los": str(money(room_before_los)),
                    "breakfast": str(money(breakfast)),
                    "los_discount": str(discount),
                    "season_factor": str(season),
                    "weekend_factor": str(weekend),
                    "occupancy": str(occupancy.quantize(Decimal("0.0001"))),
                    "yield_factor": str(yield_factor.quantize(Decimal("0.0001"))),
                }
            )
            line_items.extend(
                self.taxes.for_night(
                    net,
                    night,
                    hotel.pricing_stars,
                    coastal=hotel.coastal,
                    consecutive_night=index + 1,
                )
            )
        total = money(base + sum((item.amount for item in line_items), Decimal(0)))
        warnings = [
            "Tax bases include secondary-confidence model assumptions; see data/tax_rules.yaml.",
            "Future tax dates repeat researched baseline; future law is unverified.",
        ]
        if hotel.stars is None:
            warnings.append(UNKNOWN_STARS)
            warnings.append(
                "Tourism Dirham category uses an estimated star class, not verified classification."
            )
        result = {
            "hotel_id": hotel.id,
            "checkin": checkin.isoformat(),
            "nights": nights,
            "guests": guests,
            "plan": plan.value,
            "room_type": room_type.value,
            "bedrooms": 1,
            "currency": "AED",
            "base": str(money(base)),
            "line_items": [item.model_dump(mode="json") for item in line_items],
            "total": str(total),
            "nightly": nightly,
            "area_model": area,
            "stars_used": hotel.pricing_stars,
            "stars_basis": "osm_tag" if hotel.stars is not None else "estimate",
            "engine_version": ENGINE_VERSION,
            "calibration": calibration,
            "synthetic": True,
            "disclosure": DISCLOSURE,
            "tax_rules_as_of": self.taxes.data["as_of"],
            "warnings": warnings,
        }
        identity = {
            "seed": self.seed,
            "hotel": hotel.model_dump(),
            "tax_rules_sha256": self.taxes.fingerprint,
            "quote": result,
        }
        result["rate_id"] = (
            "rt_"
            + hashlib.sha256(
                json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
        )
        result["computed_at"] = datetime.now(UTC).isoformat()
        return result

    @staticmethod
    def room_types() -> list[dict]:
        return [
            {"id": room.value, "capacity": capacity, "bedrooms": 1, "synthetic": True}
            for room, capacity in CAPACITY.items()
        ]


def quote(
    hotel: Hotel | str,
    checkin: date,
    nights: int,
    guests: int,
    plan: Plan | str = Plan.REFUNDABLE,
    **kwargs,
) -> dict:
    """Convenient pure-price entry point; live holds use the API's shared Inventory."""
    return RateEngine().quote(hotel, checkin, nights, guests, plan, **kwargs)

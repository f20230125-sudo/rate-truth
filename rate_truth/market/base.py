"""Common provider interface. Monetary observations are nightly, one room/two adults."""

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlsplit

XOTELO = "Booking sites via TripAdvisor (Xotelo)"
SERPAPI = "Google Hotels (via SerpApi)"


class MarketError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def safe_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"https", "http"} and parsed.hostname else None
    except ValueError:
        return None


def compact_property(prop):
    """Only identity fields belong in the published match index."""
    return {
        "key": prop.get("key") or prop.get("property_token"),
        "name": prop["name"],
        "geo": prop.get("geo") or prop.get("gps_coordinates"),
    }


def amount(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


@dataclass
class Observation:
    provider: str
    hotel_key: str
    name: str
    lat: float
    lon: float
    checkin: str
    checkout: str
    currency_original: str
    amount_original: str
    amount_aed: str
    aed_conversion: dict
    taxes_included: bool | None
    per_source: list[dict]
    fetched_at: str
    query: str
    before_tax_aed: str | None = None
    lowest_all_in_aed: str | None = None
    total_all_in_aed: str | None = None
    tax_label: str = ""
    property_token: str | None = None
    link: str | None = None
    hotel_class: int | str | None = None
    # Retain source evidence, not credentials; per-source original USD stays intact.
    evidence: dict = field(default_factory=dict)

    def output(self):
        result = asdict(self)
        result["link"] = safe_url(self.link)
        return result

    def __post_init__(self):
        self.link = safe_url(self.link)


class Provider(Protocol):
    label: str

    def observe(self, hotel: dict, checkin: date, checkout: date) -> Observation | None: ...

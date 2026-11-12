"""Shared input validation and exact monetary representation."""

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FILS = Decimal("0.01")
Money = Annotated[Decimal, Field(ge=0, decimal_places=2)]
HotelID = Annotated[str, Field(pattern=r"^(node|way|relation)/[1-9][0-9]{0,19}$")]


def money(value: Decimal | str | int) -> Decimal:
    return Decimal(value).quantize(FILS, rounding=ROUND_HALF_UP)


def dubai_today() -> date:
    return datetime.now(timezone(timedelta(hours=4))).date()


class Plan(StrEnum):
    REFUNDABLE = "refundable"
    NON_REFUNDABLE = "non_refundable"
    REFUNDABLE_BREAKFAST = "refundable_breakfast"
    NON_REFUNDABLE_BREAKFAST = "non_refundable_breakfast"


class RoomType(StrEnum):
    STANDARD = "standard"
    DELUXE = "deluxe"
    FAMILY = "family"


CAPACITY = {RoomType.STANDARD: 2, RoomType.DELUXE: 3, RoomType.FAMILY: 8}


class Hotel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    id: HotelID
    name: str = Field(min_length=1, max_length=2000)
    name_en: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    stars: int | None = Field(default=None, ge=1, le=5)
    stars_tag: str | None = None
    stars_estimated: int | None = Field(default=None, ge=1, le=5)
    stars_estimation_method: str | None = None
    website: str | None = None
    area: str | None = None
    area_source: str | None = None
    stars_description: str | None = None
    coastal: bool | None = None  # Official relief eligibility is not inferable from OSM distance.

    @field_validator("website")
    @classmethod
    def safe_website(cls, value):
        if not value:
            return None
        value = value.strip()
        if value.startswith("www."):
            value = "https://" + value
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname else None

    @property
    def pricing_stars(self) -> int:
        return self.stars or self.stars_estimated or 3


class StayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hotel_id: HotelID
    checkin: date
    nights: int = Field(default=1, ge=1, le=30)
    guests: int = Field(default=2, ge=1, le=8)
    plan: Plan = Plan.REFUNDABLE
    room_type: RoomType | None = None
    as_of: date | None = None

    @field_validator("nights", "guests", mode="before")
    @classmethod
    def reject_boolean_counts(cls, value):
        if isinstance(value, bool):
            raise ValueError("counts must be integers, not booleans")
        return value

    @model_validator(mode="after")
    def validate_stay(self):
        if self.room_type is None:
            self.room_type = min(
                (room for room, capacity in CAPACITY.items() if capacity >= self.guests),
                key=CAPACITY.__getitem__,
            )
        today = dubai_today()
        if self.as_of is not None:
            if not date(2025, 1, 1) <= self.as_of <= today:
                raise ValueError("as_of must be a historical model date through today")
            today = self.as_of
        if not today <= self.checkin <= today + timedelta(days=365):
            raise ValueError("checkin must be within 0–365 days of today in Dubai")
        if self.guests > CAPACITY[self.room_type]:
            raise ValueError("guests exceed room capacity")
        return self


class HoldRequest(StayRequest):
    confirm: bool = Field(strict=True)

    @model_validator(mode="after")
    def no_historical_holds(self):
        if self.as_of is not None:
            raise ValueError("historical replay cannot create holds")
        return self

    @field_validator("confirm")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("confirm=true is required for a mock hold")
        return value


class HotelListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=100_000)
    name: str | None = Field(default=None, max_length=200)


class LineItem(BaseModel):
    rule_id: str
    name: str
    date: date
    amount: Money
    taxable_base: Money
    source: str
    accessed: date
    confidence: str
    base_confidence: str
    remittance_rule_id: str | None = None
    remittance_status: str = "normal"

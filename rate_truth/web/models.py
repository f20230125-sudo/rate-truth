"""Public response models. These generate docs/schemas for the browser fixtures too."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, field_validator

Money = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$")]
Count = Annotated[int, Field(ge=0)]
Confidence = Literal["official", "secondary", "uncertain"]


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Line(Model):
    label: str
    amount: Money
    rule_id: str
    kind: Literal["base", "tax", "fee", "discount"]
    basis: str | None = None
    source_url: str | None = None
    confidence: Confidence | None = None


class Folio(Model):
    rate_id: str
    computed_at: datetime
    hotel_id: str
    hotel_name: str
    checkin: date
    nights: Annotated[int, Field(ge=1, le=30)]
    guests: Annotated[int, Field(ge=1, le=8)]
    room: str
    plan: str
    refundable: bool
    breakfast: bool
    lines: list[Line]
    total: Money
    currency: Literal["AED"]
    tax_rules_as_of: date
    synthetic: Literal[True]


class Place(Model):
    name: str
    metres: Annotated[float, Field(ge=0)]


class Hotel(Model):
    id: str
    osm_id: str
    osm_type: Literal["node", "way", "relation"]
    name: str
    name_en: str | None
    mapped_osm_ids: list[str]
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    area: str | None
    stars: int | None
    stars_estimated: int | None
    stars_method: str | None
    website: str | None
    nearest_metro: Place | None
    nearest_beach: Place | None
    landmarks: list[Place]


class HotelRow(Hotel):
    from_folio: Folio | None


class Hotels(Model):
    total: Count
    items: list[HotelRow]


class Fact(Model):
    text: str
    source: str


class Card(Model):
    facts: list[Fact]


class Availability(Model):
    date: date
    rooms_left: Count
    from_total: Money | None


class HotelDetail(Model):
    hotel: Hotel
    card: Card
    tonight: Folio | None
    availability: list[Availability]


class Meta(Model):
    hotels: Count
    pois: Count
    osm_fetched_at: datetime
    tax_rules_version: str
    xsd_fetched_at: datetime
    eval_run_at: datetime | None
    llm_mode: Literal["live", "replay"]
    retrieval_mode: Literal["bm25", "hybrid"]
    mcp_url: str


class Turn(Model):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(max_length=6000)]


class AskRequest(Model):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: Annotated[str, Field(min_length=1, max_length=600)]
    history: Annotated[list[Turn], Field(max_length=8)] = []


class Trace(Model):
    step: Count
    tool: str
    args: dict[str, Any]
    started_ms: Annotated[int, Field(ge=0)]
    duration_ms: Annotated[int, Field(ge=0)]
    ok: bool
    summary: str
    rate_ids: list[str]


class Price(Model):
    amount: Money
    rate_id: str | None
    traced: bool


class Answer(Model):
    text: str
    prices: list[Price]
    folios: list[Folio]
    cited_cards: list[str]


class Grounding(Model):
    traced: Count
    total: Count
    ok: bool
    cards_ok: bool
    untraced: list[Money]


class HoldRequest(Model):
    rate_id: str
    hold_token: Annotated[str, Field(min_length=32, max_length=4096)]
    folio: Folio


class HoldBody(Model):
    model_config = ConfigDict(extra="forbid")
    rate_id: Annotated[str, Field(min_length=1, max_length=200)]
    hold_token: Annotated[str, Field(min_length=32, max_length=4096)]
    confirm: StrictBool = Field(json_schema_extra={"const": True})

    @field_validator("confirm")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("requires confirm=true from the UI")
        return value


class Hold(Model):
    folio: Folio
    hold_id: str
    expires_at: datetime
    mock: Literal[True]


class StreamError(Model):
    code: str
    message: str
    retry_after_s: int | None = None
    field: str | None = None
    rule: str | None = None


class Error(Model):
    error: StreamError


class Done(Model):
    mode: Literal["live", "replay"]
    model: str | None
    steps: Count
    total_ms: Count


class Difference(Model):
    label: str
    feed: Money | None
    landing: Money | None


class Sample(Model):
    id: str
    hotel_id: str
    hotel_name: str
    checkin: date
    nights: Count
    feed: Folio
    landing: Folio
    match: bool
    diff: list[Difference]
    reason: str | None
    reason_label: str | None
    injected: str | None
    detected_reason: str | None


class Accuracy(Model):
    score: Annotated[float, Field(ge=0, le=1)]
    definition: str
    samples: list[Sample]
    by_reason: dict[str, Count]
    faults: list[str]


class Source(Model):
    label: str
    url: str


class Fault(Model):
    id: str
    label: str
    description: str
    google_reason: str
    sources: list[Source]


class Faults(RootModel[list[Fault]]):
    pass


class FeedError(Model):
    line: Count | None
    message: str


class Feed(Model):
    kind: Literal["hotel_list", "property_data", "transaction", "ari_rate", "ari_avail", "ari_inv"]
    filename: str
    bytes: Count
    schema_url: str | None
    xsd_fetched_at: datetime | None
    valid: bool
    check: Literal["xsd", "structural"]
    errors: list[FeedError]


class Feeds(Model):
    items: list[Feed]


class TaxRule(Model):
    id: str
    label: str
    kind: Literal["percent", "per_room_night"]
    value: str
    base: str
    applies_from: date
    applies_to: date | None
    status: Literal["in_force", "suspended", "uncertain", "ended"]
    source_url: str
    accessed: str
    confidence: Confidence
    note: str


class Scenario(Model):
    id: str
    label: str
    description: str


class Taxes(Model):
    rules: list[TaxRule]
    scenarios: list[Scenario]


class Eval(Model):
    model_config = ConfigDict(extra="allow")
    run_at: datetime | None


EVENTS = {
    "trace": Trace,
    "answer": Answer,
    "grounding": Grounding,
    "hold_request": HoldRequest,
    "error": StreamError,
    "done": Done,
}


class MarketSource(Model):
    site: str
    amount: Money
    currency: Literal["AED"]
    amount_original: str | None = None
    currency_original: Literal["USD"] | None = None
    tax_original: str | None = None
    before_tax: float | None = None
    after_tax: float | None = None


class MarketObservation(Model):
    provider: Literal["Booking sites via TripAdvisor (Xotelo)", "Google Hotels (via SerpApi)"]
    hotel_key: str
    name: str
    lat: float
    lon: float
    checkin: date
    checkout: date
    currency_original: Literal["USD", "AED"]
    amount_original: str
    amount_aed: Money
    aed_conversion: dict[str, Any]
    taxes_included: bool | None
    tax_label: str
    before_tax_aed: Money | None
    lowest_all_in_aed: Money | None
    total_all_in_aed: Money | None
    per_source: list[MarketSource]
    fetched_at: datetime
    query: str
    age_hours: float
    match_score: float | None
    property_token: str | None
    link: str | None
    hotel_class: int | str | None
    evidence: dict[str, Any]
    disclosure: Literal["observed price, not a quote"]


class MarketProvider(Model):
    provider: Literal["Booking sites via TripAdvisor (Xotelo)", "Google Hotels (via SerpApi)"]
    observation: MarketObservation | None
    parity: dict[str, Any] | None = None
    message: str | None = None
    error: StreamError | None = None


class MarketCheck(Model):
    hotel_id: str
    checkin: date
    nights: Annotated[int, Field(ge=1, le=30)]
    currency: Literal["AED"]
    live_requested: bool
    providers: list[MarketProvider]
    supplier_quote: dict[str, Any]
    disclosure: Literal["observed price, not a quote"]


class ProviderSummary(Model):
    provider: str
    matched_hotels: Count
    observations: Count
    enabled: bool


class MarketBudget(Model):
    month: str
    used: Count
    cap: Literal[220]
    remaining: Count


class MarketSummary(Model):
    snapshot_date: str | None
    observations: Count
    matched_hotels: Count
    hotels_with_observations: Count
    providers: list[ProviderSummary]
    budget: MarketBudget
    disclosure: Literal["observed price, not a quote"]


class MCPRequest(Model):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


class MCPResponse(Model):
    jsonrpc: Literal["2.0"]
    id: str | int | None
    result: Any = None
    error: dict[str, Any] | None = None

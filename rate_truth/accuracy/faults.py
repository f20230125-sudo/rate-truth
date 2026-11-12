"""Deliberate, request-local feed corruption for diagnostics; never change supplier state."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

from rate_truth.supplier.models import money
from rate_truth.supplier.taxes import TaxRules

GOOGLE_REASONS = (
    "https://developers.google.com/hotels/hotel-prices/api-reference/rest/v3/"
    "accounts.priceAccuracyViews#MismatchReason"
)
PRESS = (
    "https://www.thenationalnews.com/business/economy/2026/05/21/"
    "dubai-approves-dh15-billion-relief-package-including-halting-hotel-and-restaurant-tax/"
)
OFFICIAL = TaxRules().data["evidence"]["relief"]["source"]
FAULTS = [
    {
        "id": "stale_cache",
        "label": "Stale cache",
        "google_reason": "PRICE_FEED_DELAYED",
        "description": "An older cached supplier snapshot advertises a different base.",
    },
    {
        "id": "missing_discount",
        "label": "Missing LOS discount",
        "google_reason": "DISCOUNT_MISSING",
        "description": "Feed forgets the supplier's length-of-stay discount.",
    },
    {
        "id": "taxes_fees_omitted",
        "label": "Taxes and fees omitted",
        "google_reason": "TAX_MISMATCH",
        "description": "Feed drops mandatory tax and fee lines.",
    },
    {
        "id": "currency_rounding",
        "label": "Currency rounding",
        "google_reason": "MISMATCH_REASON_UNSPECIFIED",
        "description": "Double conversion loses AED 0.02.",
    },
    {
        "id": "los_mismatch",
        "label": "Wrong length of stay",
        "google_reason": "WRONG_ITINERARY",
        "description": "Feed itinerary uses a different number of nights.",
    },
    {
        "id": "hotel_not_listed",
        "label": "Hotel not listed",
        "google_reason": "SITE_ERROR",
        "description": "Feed hotel is absent from the hotel list.",
    },
    {
        "id": "tax_rule_change_missed",
        "label": "Remittance relief misread as guest exemption",
        "google_reason": "TAX_MISMATCH",
        "description": "Feed mistakes hotel remittance relief for a guest fee exemption.",
        "sources": [
            {"label": "The National, 21 May 2026", "url": PRESS},
            {"label": "Resolution 40/2026 (official, Arabic)", "url": OFFICIAL},
        ],
    },
]
for fault in FAULTS:
    fault.setdefault("sources", [])
FAULT_IDS = {f["id"] for f in FAULTS}


def inject(folio, fault, *, official_source=OFFICIAL, cached=None):
    if fault not in FAULT_IDS:
        raise ValueError("unknown fault")
    f = deepcopy(folio)
    evidence = {}
    if fault == "stale_cache":
        f["computed_at"] = (
            datetime.fromisoformat(f["computed_at"]) - timedelta(days=2)
        ).isoformat()
        if cached is None:
            raise ValueError("stale_cache requires an actual cached computation")
        f["lines"] = deepcopy(cached["lines"])
    elif fault == "missing_discount":
        discount = Decimal("0.10") if f["nights"] >= 7 else Decimal("0.05")
        for line in f["lines"]:
            if line["kind"] == "base":
                line["amount"] = str(money(Decimal(line["amount"]) / (1 - discount)))
    elif fault in {"taxes_fees_omitted", "tax_rule_change_missed"}:
        f["lines"] = [
            line
            for line in f["lines"]
            if (
                line["label"] != "Service charge"
                if fault == "taxes_fees_omitted"
                else line["label"] not in {"Municipality fee", "Tourism Dirham"}
            )
        ]
        if fault == "tax_rule_change_missed":
            evidence = {
                "press_source": PRESS,
                "official_source": official_source,
                "policy_misreading": "remittance exemption treated as guest exemption",
            }
    elif fault == "currency_rounding":
        f["lines"][0]["amount"] = str(money(Decimal(f["lines"][0]["amount"]) + Decimal("0.02")))
    elif fault == "los_mismatch":
        f["nights"] += 1
    elif fault == "hotel_not_listed":
        evidence["listed"] = False
    f["total"] = str(money(sum((Decimal(i["amount"]) for i in f["lines"]), Decimal(0))))
    return f, evidence

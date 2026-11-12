"""Single supplier-to-public-contract adapter; money never passes through floats."""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from rate_truth.geo import UNKNOWN_STARS
from rate_truth.settings import PUBLIC_API_URL
from rate_truth.supplier.models import Hotel, money

DUBAI = timezone(timedelta(hours=4))
LABELS = {
    "service_charge": "Service charge",
    "municipality": "Municipality fee",
    "vat": "VAT",
    "tourism_dirham": "Tourism Dirham",
}
BASES = {
    "service_charge": "10% of room rate",
    "municipality": "7% of room rate",
    "vat": "5% of room rate + service charge",
}


def folio(quote: dict, hotel: Hotel) -> dict:
    lines = []
    for night in quote["nightly"]:
        day = datetime.fromisoformat(night["date"])
        basis = "Discounted room rate" + (
            " including breakfast" if quote["plan"].endswith("breakfast") else ""
        )
        basis += "; " + quote.get("calibration", {}).get(
            "basis", "base from published Dubai ADR calibration"
        )
        if hotel.stars is None:
            basis += f"; {UNKNOWN_STARS}"
        lines.append(
            {
                "label": f"Room rate {day.day} {day:%b}",
                "amount": night["base"],
                "rule_id": quote["engine_version"],
                "kind": "base",
                "basis": basis,
                "source_url": PUBLIC_API_URL + "/docs/supplier-model.md",
                "confidence": "uncertain",
            }
        )
    grouped = OrderedDict()
    for item in quote["line_items"]:
        grouped.setdefault(item["rule_id"], []).append(item)
    for rule_id, items in grouped.items():
        first = items[0]
        kind = first["name"]
        basis = BASES.get(kind)
        if kind == "tourism_dirham":
            unit = money(first["amount"])
            basis = f"{len(items)} × AED {unit.normalize():f}"
        confidence = first["confidence"]
        if first["base_confidence"] != "official":
            confidence = "secondary"
        if kind == "tourism_dirham" and hotel.stars is None:
            confidence = "uncertain"
            basis += f"; {UNKNOWN_STARS}"
        lines.append(
            {
                "label": LABELS[kind],
                "amount": str(money(sum((Decimal(i["amount"]) for i in items), Decimal(0)))),
                "rule_id": rule_id,
                "kind": "fee" if kind == "service_charge" else "tax",
                "basis": basis,
                "source_url": first["source"],
                "confidence": confidence,
            }
        )
    return {
        "rate_id": quote["rate_id"],
        "computed_at": datetime.fromisoformat(quote["computed_at"]).astimezone(DUBAI).isoformat(),
        "hotel_id": hotel.id,
        "hotel_name": hotel.name,
        "checkin": quote["checkin"],
        "nights": quote["nights"],
        "guests": quote["guests"],
        "room": quote["room_type"],
        "plan": quote["plan"],
        "refundable": not quote["plan"].startswith("non_refundable"),
        "breakfast": quote["plan"].endswith("breakfast"),
        "lines": lines,
        "total": quote["total"],
        "currency": "AED",
        "tax_rules_as_of": quote["tax_rules_as_of"],
        "synthetic": True,
    }

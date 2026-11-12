"""Pull pricing from supplier Folios; Custom1/2 carry rate_id and computed_at."""

import json
from decimal import Decimal

from rate_truth.contract import folio
from rate_truth.feeds.common import Feed, element, transaction_root
from rate_truth.geo import UNKNOWN_STARS
from rate_truth.supplier.models import money


def build(engine, stays):
    folios = []
    for stay in stays:
        hotel = engine.catalog.get(stay.hotel_id)
        quote = engine.quote(
            hotel,
            stay.checkin,
            stay.nights,
            stay.guests,
            stay.plan,
            stay.room_type,
            as_of=stay.as_of,
        )
        f = folio(quote, hotel)
        folios.append(f)
    return from_folios(folios)


def from_folios(folios, *, audit_evidence=False):
    """Serialize supplier Folios, or explicitly labelled audit-only fault copies."""
    root = transaction_root()
    for f in folios:
        result = element(root, "Result")
        element(result, "Property", f["hotel_id"])
        element(result, "Checkin", f["checkin"])
        element(result, "Nights", f["nights"])
        element(result, "RoomID", f["room"])
        element(result, "RatePlanID", f["plan"])
        for tag, kind in (("Baserate", "base"), ("Tax", "tax"), ("OtherFees", "fee")):
            amount = sum(
                (Decimal(i["amount"]) for i in f["lines"] if i["kind"] == kind), Decimal(0)
            )
            element(result, tag, str(money(amount)), currency="AED")
        refund = {"available": str(f["refundable"]).lower()}
        if f["refundable"]:
            refund.update(refundable_until_days="1", refundable_until_time="18:00:00")
        element(result, "Refundable", **refund)
        element(result, "BreakfastIncluded", str(f["breakfast"]).lower())
        element(result, "Custom1", f["rate_id"])
        element(result, "Custom2", f["computed_at"])
        element(result, "Custom3", "SYNTHETIC")
        if any(UNKNOWN_STARS in line.get("basis", "") for line in f["lines"]):
            element(result, "Custom4", UNKNOWN_STARS)
        element(result, "Occupancy", f["guests"])
        if audit_evidence:
            # Public serialized breakdown, never the injector label or metadata.
            element(result, "Custom5", json.dumps(f, ensure_ascii=False))
    return Feed.create("transaction", root, folios)


def audit_folios(feed):
    """Read audit evidence exclusively from the serialized transaction."""
    from rate_truth.feeds.validate import parse

    result = []
    for node, aggregate in zip(parse(feed.xml).findall("Result"), prices(feed), strict=True):
        f = json.loads(node.findtext("Custom5"))
        f.update(aggregate)
        f["guests"] = int(node.findtext("Occupancy"))
        f["room"] = node.findtext("RoomID")
        f["plan"] = node.findtext("RatePlanID")
        for tag, kind in (("Baserate", "base"), ("Tax", "tax"), ("OtherFees", "fee")):
            total = sum((Decimal(i["amount"]) for i in f["lines"] if i["kind"] == kind), Decimal(0))
            if total != Decimal(node.findtext(tag)):
                raise ValueError("serialized audit breakdown disagrees with price")
        result.append(f)
    return result


def prices(feed):
    from rate_truth.feeds.validate import parse

    return [
        {
            "hotel_id": r.findtext("Property"),
            "checkin": r.findtext("Checkin"),
            "nights": int(r.findtext("Nights")),
            "rate_id": r.findtext("Custom1"),
            "computed_at": r.findtext("Custom2"),
            "total": str(
                money(
                    sum(
                        (Decimal(r.findtext(t)) for t in ("Baserate", "Tax", "OtherFees")),
                        Decimal(0),
                    )
                )
            ),
        }
        for r in parse(feed.xml).findall("Result")
    ]

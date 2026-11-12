"""Matched nightly pre-tax anchors; the user's provider precedence is explicit here."""

from datetime import date
from decimal import Decimal
from statistics import median

from rate_truth.market.base import SERPAPI, XOTELO, amount
from rate_truth.market.storage import utcnow, write_json
from rate_truth.settings import DATA
from rate_truth.supplier.models import money


def back_compute(all_in, taxes, night, stars):
    """Invert the actual effective-dated, rounded stack to the nearest attainable fils.

    A derived value is not a stated pre-tax observation. Kept for explicit analysis;
    automatic anchors follow SerpApi pre-tax -> Xotelo median -> published ADR.
    """
    target = amount(all_in)
    if target is None:
        raise ValueError("invalid all-in amount")

    def total(fils):
        base = Decimal(fils) / 100
        return base + sum(i.amount for i in taxes.for_night(base, night, stars))

    low, high = 0, int(target * 100)
    while low < high:
        mid = (low + high) // 2
        if total(mid) < target:
            low = mid + 1
        else:
            high = mid
    candidates = {low, max(0, low - 1)}
    selected = min(candidates, key=lambda v: (abs(total(v) - target), v))
    return {
        "amount": str(money(Decimal(selected) / 100)),
        "basis": "derived",
        "residual_aed": str(money(total(selected) - target)),
    }


def derive_anchors(records):
    groups = {}
    for row in records:
        if row.get("hotel_id") and row.get("observation"):
            groups.setdefault(row["hotel_id"], []).append(row["observation"])
    anchors = {}
    for hotel_id, observations in groups.items():
        choices = []
        for o in observations:
            value, priority, basis = None, 9, ""
            if o["provider"] == SERPAPI and amount(o.get("before_tax_aed")) is not None:
                value, priority = amount(o["before_tax_aed"]), 0
                basis = "stated pre-tax"
            elif o["provider"] == XOTELO:
                if (date.fromisoformat(o["checkout"]) - date.fromisoformat(o["checkin"])).days != 1:
                    continue  # Multi-night provider amount semantics remain unverified.
                sources = o.get("per_source") or []
                values = [amount(s.get("amount")) for s in sources]
                if (
                    values
                    and all(v is not None for v in values)
                    and all(s.get("tax_original") is None for s in sources)
                ):
                    value, priority = median(values), 1
                    basis = "assumed pre-tax; source does not state taxes"
            if value is not None and value > 0:
                choices.append((priority, o["fetched_at"], o, value, basis))
        if not choices:
            continue  # Published-ADR calibration remains in force.
        # Latest observation within the best available provider priority.
        priority = min(c[0] for c in choices)
        _, _, chosen, value, basis = max(
            (c for c in choices if c[0] == priority), key=lambda c: c[1]
        )
        anchors[hotel_id] = {
            "anchor_aed": str(money(value)),
            "provider": chosen["provider"],
            "basis": basis,
            "reference_checkin": chosen["checkin"],
            "fetched_at": chosen["fetched_at"],
            "hotel_key": chosen["hotel_key"],
            "query": chosen["query"],
            "reference_nights": (
                date.fromisoformat(chosen["checkout"]) - date.fromisoformat(chosen["checkin"])
            ).days,
        }
    return {"schema_version": 1, "generated_at": utcnow().isoformat(), "anchors": anchors}


def write_calibration(records, path=None):
    payload = derive_anchors(records)
    write_json(path or DATA / "calibration_market.json", payload)
    return payload

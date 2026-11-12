"""Compare serialized Pull prices to the supplier HTTP /quote endpoint, offline."""

import random
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from rate_truth.accuracy.classify import classify, matches
from rate_truth.accuracy.faults import FAULT_IDS, inject
from rate_truth.contract import folio
from rate_truth.feeds.hotel_list import build as build_list
from rate_truth.feeds.transaction import audit_folios, build, from_folios, prices
from rate_truth.feeds.validate import parse
from rate_truth.supplier.booking_api import create_app
from rate_truth.supplier.models import StayRequest, dubai_today
from rate_truth.supplier.rates import RateEngine

DEFINITION = (
    "Our local score, not Google's score: share of samples with matching property/itinerary "
    "and an all-in total within 1% or AED 1 of supplier /quote (whichever is larger)."
)


def diff(feed, landing):
    def lines(f):
        result = {i["label"]: i["amount"] for i in f["lines"]}
        result["Total"] = f["total"]
        return result

    a, b = lines(feed), lines(landing)
    return [
        {"label": label, "feed": a.get(label), "landing": b.get(label)}
        for label in dict.fromkeys([*a, *b])
        if a.get(label) != b.get(label)
    ]


def audit(engine, *, n=30, seed=2026, faults=()):
    if type(n) is not int or not 1 <= n <= 100 or set(faults) - FAULT_IDS:
        raise ValueError("invalid audit bounds or fault")
    rng = random.Random(seed)
    hotels = sorted(engine.catalog.hotels.values(), key=lambda h: h.id)
    samples = []
    # A small sampled panel lets 2-3 missing properties produce both positive and
    # negative observations in a 30-row audit, rather than a 3/737 lottery.
    panel = rng.sample(hotels, min(12, len(hotels)))
    missing_ids = {h.id for h in panel[:3]}
    hotel_list_xml = build_list(panel).xml
    ground_truth = {}
    injected_counts = Counter()
    # An earlier deterministic inventory/yield revision is our explicit cached supplier
    # computation. Some itineraries have unchanged totals and must stay clean.
    cached_engine = RateEngine(
        seed=engine.seed - 1,
        catalog=engine.catalog,
        taxes=engine.taxes,
        market_calibration={"anchors": engine.market_anchors},
    )
    with TestClient(create_app(engine)) as client:
        for index in range(n):
            # Same stay mix for clean and dirty audits. Include both relief phases and controls.
            historical = (date(2026, 5, 1), date(2026, 8, 1), date(2026, 10, 1))
            as_of = historical[index % 3] if index % 4 == 0 else None
            start = as_of or dubai_today()
            hotel = panel[index % len(panel)]
            stay = StayRequest(
                hotel_id=hotel.id,
                checkin=start + timedelta(days=rng.randrange(20)),
                nights=(1, 2, 3, 4, 7)[index % 5],
                guests=2,
                as_of=as_of,
            )
            artifact = build(engine, [stay])
            parsed = prices(artifact)[0]
            feed = artifact.folios[0]
            assert parsed["total"] == feed["total"] and parsed["rate_id"] == feed["rate_id"]
            params = stay.model_dump(mode="json", exclude_none=True)
            response = client.get("/quote", params=params)
            response.raise_for_status()
            landing = folio(response.json(), hotel)
            cached = folio(
                cached_engine.quote(hotel, stay.checkin, stay.nights, stay.guests, as_of=as_of),
                hotel,
            )
            eligible = {
                "stale_cache": index % 4 == 0 and cached["total"] != landing["total"],
                "missing_discount": stay.nights >= 3 and index % 2 == 0,
                "los_mismatch": stay.nights > 1 and index % 3 == 0,
                "hotel_not_listed": hotel.id in missing_ids and (len(panel) > 3 or index % 3 == 0),
                "taxes_fees_omitted": index % 4 == 0,
                "tax_rule_change_missed": (
                    date(2026, 4, 1) <= stay.checkin <= date(2026, 6, 30)
                    or date(2026, 7, 1) <= stay.checkin <= date(2026, 9, 30)
                    and hotel.coastal is False
                ),
                "currency_rounding": int(Decimal(landing["total"]) * 100) % 10 >= 7,
            }
            choices = sorted(f for f in set(faults) if eligible[f])
            if choices:
                least = min(injected_counts[f] for f in choices)
                choices = [f for f in choices if injected_counts[f] == least]
            fault = random.Random(f"{seed}:{index}:fault").choice(choices) if choices else None
            if fault:
                injected_counts[fault] += 1
            ground_truth[f"sample-{seed}-{index}"] = fault
            if fault:
                feed, _ = inject(
                    feed,
                    fault,
                    official_source=engine.taxes.data["evidence"]["relief"]["source"],
                    cached=cached,
                )
            # Compare the values that actually survived XML serialization, including faults.
            transaction = from_folios([feed], audit_evidence=True)
            feed = audit_folios(transaction)[0]
            listing = parse(hotel_list_xml)
            if fault == "hotel_not_listed":
                for node in listing.findall("listing"):
                    if node.findtext("id") == hotel.id:
                        listing.remove(node)
            from lxml import etree

            serialized_list = etree.tostring(listing, encoding="unicode")
            diagnosis = classify(
                feed, landing, hotel_list_xml=serialized_list, tax_rules=engine.taxes.data
            )
            match = matches(feed, landing, hotel_list_xml=serialized_list)
            samples.append(
                {
                    "id": f"sample-{seed}-{index}",
                    "hotel_id": hotel.id,
                    "hotel_name": hotel.name,
                    "checkin": stay.checkin.isoformat(),
                    "nights": stay.nights,
                    "feed": feed,
                    "landing": landing,
                    "hotel_list_xml": serialized_list,
                    "feed_xml": transaction.xml.decode(),
                    "match": match,
                    "diff": diff(feed, landing),
                    "reason": diagnosis["reason"],
                    "reason_label": diagnosis["diagnosis"],
                    "injected": fault,
                    "detected_reason": diagnosis["diagnosis"],
                    "evidence": diagnosis["evidence"],
                    "injection_note": "Deliberately corrupted feed; "
                    "rate_id references original supplier quote"
                    if fault
                    else None,
                }
            )
    positives = sum(v is not None for v in ground_truth.values())
    true_positives = sum(
        s["detected_reason"] == ground_truth[s["id"]] for s in samples if ground_truth[s["id"]]
    )
    detections = sum(s["detected_reason"] is not None for s in samples)
    return {
        "score": sum(s["match"] for s in samples) / len(samples),
        "definition": DEFINITION,
        "samples": samples,
        "by_reason": dict(Counter(s["reason"] for s in samples if s["reason"])),
        "faults": list(faults),
        "detection": {
            "injected": positives,
            "detected": detections,
            "true_positives": true_positives,
            "precision": true_positives / detections if detections else None,
            "recall": true_positives / positives if positives else None,
        },
    }

"""Code-side price grounding: folio totals/lines in this turn are the only price evidence."""

import re
from decimal import Decimal

NUMBER = r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.])"
MENTION = re.compile(
    rf"\bAED\s*(?P<a>{NUMBER})(?:\s*(?:[-–—]|to)\s*(?:AED\s*)?(?P<b>{NUMBER}))?"
    rf"|(?P<c>{NUMBER})(?:\s*(?:[-–—]|to)\s*(?P<d>{NUMBER}))?\s*AED\b",
    re.I,
)


def amounts(text):
    return [
        format(Decimal(value.replace(",", "")), ".2f")
        for match in MENTION.finditer(text)
        for value in match.groups()
        if value is not None
    ]


def folios_in(value):
    found = {}

    def walk(node):
        if isinstance(node, dict):
            if {"rate_id", "total", "lines", "synthetic", "hotel_id"} <= node.keys():
                found[node["rate_id"]] = node
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return list(found.values())


def normalise_citations(citations, outputs):
    def canonical(value):
        if isinstance(value, str) and re.fullmatch(r"(?:osm:)?(?:node|way|relation)/\d+", value):
            return "osm:" + value.removeprefix("osm:")
        return None

    seen = set()

    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif card := canonical(value):
            seen.add(card)

    walk(outputs)
    valid = [canonical(c) for c in citations if canonical(c) in seen]
    return list(dict.fromkeys(valid)), len(valid) == len(citations)


def ground(text, outputs, cited_cards=()):
    folios = folios_in(outputs)
    evidence = {}
    for folio in folios:
        for amount in [folio["total"], *(line["amount"] for line in folio["lines"])]:
            evidence.setdefault(Decimal(amount), folio["rate_id"])
    prices = []
    originals = [
        Decimal(v.replace(",", ""))
        for m in MENTION.finditer(text)
        for v in m.groups()
        if v is not None
    ]
    for value, original in zip(amounts(text), originals, strict=True):
        rate_id = evidence.get(original) if original == Decimal(value) else None
        prices.append({"amount": value, "rate_id": rate_id, "traced": rate_id is not None})
    untraced = [p["amount"] for p in prices if not p["traced"]]
    return (
        prices,
        folios,
        {
            "traced": len(prices) - len(untraced),
            "total": len(prices),
            "ok": not untraced,
            "cards_ok": normalise_citations(cited_cards, outputs)[1],
            "untraced": untraced,
        },
    )

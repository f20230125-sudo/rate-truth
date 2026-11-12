"""Conservative name AND <=250 m identity matching; never guess ambiguous identities."""

import re
import unicodedata
from math import isfinite

from rate_truth.geo import distance

GENERIC = {
    "hotel",
    "hotels",
    "apartment",
    "apartments",
    "suite",
    "suites",
    "inn",
    "resort",
    "resorts",
    "residence",
    "residences",
    "dubai",
    "uae",
    "by",
    "the",
    "and",
    "llc",
}


def tokens(name):
    name = unicodedata.normalize("NFKD", name).casefold()
    name = "".join(c for c in name if not unicodedata.combining(c))
    # Keep building numbers, including those joined to a word (Sunrise12).
    return set(re.findall(r"[^\W\d_]+|\d+", name))


def token_set_ratio(a, b):
    """Precision first: generic descriptors may vary; every identity token must agree.

    A typo, extra branch qualifier, chain name or number needs manual review.
    Neither a shared substring nor proximity establishes hotel identity.
    """
    left, right = tokens(a), tokens(b)

    def product(words):
        residence = bool(words & {"residence", "residences"})
        hotel = bool(words & {"hotel", "hotels"})
        if residence and not hotel:
            return "residence"
        if hotel and not residence:
            return "hotel"
        return None

    # Nearby hotel and residence products can share every brand/location token.
    # Missing descriptors or a combined Hotel & Residence name are not a conflict.
    left_product, right_product = product(left), product(right)
    if left_product and right_product and left_product != right_product:
        return 0.0
    left, right = left - GENERIC, right - GENERIC
    return float(bool(left) and left == right)


def _candidates(prop, hotels):
    geo = prop.get("geo") or prop.get("gps_coordinates") or {}
    try:
        point = {"lat": float(geo["latitude"]), "lon": float(geo["longitude"])}
        if (
            not all(isfinite(v) for v in point.values())
            or abs(point["lat"]) > 90
            or (abs(point["lon"]) > 180)
        ):
            return []
    except (ValueError, TypeError, KeyError):
        return []
    candidates = []
    for hotel in hotels:
        metres = distance(point, {"lat": hotel.lat, "lon": hotel.lon})
        if metres <= 250:
            score = token_set_ratio(str(prop.get("name") or ""), hotel.name)
            if score > 0:
                candidates.append((score, metres, hotel.id))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    return candidates


def match_property(prop, hotels, *, threshold=0.82):
    candidates = _candidates(prop, hotels)
    if not candidates or candidates[0][0] < threshold:
        return {"status": "unmatched"}
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] <= 0.05 + 1e-9:
        return {"status": "ambiguous"}
    score, metres, hotel_id = candidates[0]
    return {
        "status": "matched",
        "hotel_id": hotel_id,
        "score": round(score, 6),
        "distance_m": round(metres, 2),
    }


def match_many(properties, hotels):
    hotels = list(hotels)
    records = [{"property": prop, **match_property(prop, hotels)} for prop in properties]
    by_osm = {}
    for record in records:
        # Include every qualifying edge, even when the provider was ambiguous.
        for score, _, hotel_id in _candidates(record["property"], hotels):
            if score >= 0.82:
                by_osm.setdefault(hotel_id, []).append(record)
    for group in by_osm.values():
        keys = {
            p["property"].get("key")
            or p["property"].get("property_token")
            or p["property"].get("link")
            or p["property"]["name"]
            for p in group
        }
        if len(keys) > 1:
            for record in group:
                record["status"] = "ambiguous"
                record.pop("hotel_id", None)
    return records

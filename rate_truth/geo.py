"""OSM-only geography. Distances are straight-line metres, never walking times."""

import re
import unicodedata
from collections import Counter
from math import asin, cos, radians, sin, sqrt

UNKNOWN_STARS = "stars not tagged in OSM; priced as 3-star"
AREA_NAMES = {
    "dubai_marina": "Dubai Marina",
    "dubai_mall": "Downtown Dubai",
    "burj_khalifa": "Downtown Dubai",
    "old_dubai": "Old Dubai",
    "dxb": "Airport",
    "expo_city": "Expo City",
}


def distance(a, b) -> float:
    lat1, lat2 = radians(a["lat"]), radians(b["lat"])
    dlat, dlon = lat2 - lat1, radians(b["lon"] - a["lon"])
    return (
        6371008.8
        * 2
        * asin(min(1, sqrt(sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2)))
    )


def normalized_name(value: str) -> str:
    return "".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def dedupe_pois(pois: list[dict]) -> list[dict]:
    # Prefer nodes to bounding-box centres; then stable OSM ID ordering.
    # Match against the retained canonical point, avoiding chains spanning >400 m.
    kept = []
    for poi in sorted(pois, key=lambda p: (p["osm_type"] != "node", p["id"])):
        names = {normalized_name(n) for n in (poi["name"], poi.get("name_en")) if n}
        duplicate = next(
            (
                p
                for p in kept
                if names
                and names.intersection(
                    normalized_name(n) for n in (p["name"], p.get("name_en")) if n
                )
                and sorted(p["types"]) == sorted(poi["types"])
                and distance(p, poi) <= 400
            ),
            None,
        )
        if duplicate:
            duplicate["merged_osm_ids"] = sorted(
                set(
                    duplicate.get("merged_osm_ids", [duplicate["id"]])
                    + poi.get("merged_osm_ids", [poi["id"]])
                )
            )
        else:
            kept.append(dict(poi))
    return sorted(kept, key=lambda p: p["id"])


def enrich_hotels(hotels: list[dict], pois: list[dict]) -> list[dict]:
    landmarks = [p for p in pois if any(t in AREA_NAMES for t in p["types"])]
    result = []
    for hotel in hotels:
        h = dict(hotel)
        nearest = min(landmarks, key=lambda p: (distance(h, p), p["id"]), default=None)
        h["area"], h["area_source"] = None, None
        if nearest and distance(h, nearest) <= 2000:
            kind = next(t for t in nearest["types"] if t in AREA_NAMES)
            h["area"] = AREA_NAMES[kind]
            h["area_source"] = f"https://www.openstreetmap.org/{nearest['id']}"
        if h["stars"] is None:
            h["stars_estimated"] = 3
            h["stars_description"] = UNKNOWN_STARS
        result.append(h)
    return result


def counts(pois):
    return dict(sorted(Counter(t for p in pois for t in p["types"]).items()))

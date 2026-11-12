"""One bounded Overpass query for Dubai emirate, never a fabricated fallback.

Run with .venv/Scripts/python scripts/fetch_osm.py. No third-party dependencies.
See https://dev.overpass-api.de/overpass-doc/en/preface/commons.html.
No automatic retries: on 429/504, wait as instructed before manually retrying.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rate_truth.geo import dedupe_pois, enrich_hotels  # noqa: E402

ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "rate-truth-research/0.1 (local research snapshot; ODbL attribution retained)"
LANDMARKS = (
    "Dubai Mall|Burj Khalifa|Expo City|Expo 2020|Dubai Marina|"
    "Dubai Museum|Al Fahidi|Al Shindagha|Gold Sou[qk]|Spice Sou[qk]|"
    "Bastakiya|Bur Dubai|Deira"
)
QUERY = f'''[out:json][timeout:180][maxsize:134217728];
area["boundary"="administrative"]["ISO3166-2"="AE-DU"]->.dubai;
(
  nwr["tourism"="hotel"](area.dubai);
  nwr["railway"="station"]["station"="subway"](area.dubai);
  nwr["railway"="station"]["subway"="yes"](area.dubai);
  nwr["public_transport"="station"]["subway"="yes"](area.dubai);
  nwr["natural"="beach"](area.dubai);
  nwr["aeroway"="aerodrome"]["iata"~"^(DXB|DWC)$"](area.dubai);
  nwr["name"~"{LANDMARKS}",i](area.dubai);
  nwr["name:en"~"{LANDMARKS}",i](area.dubai);
);
out center tags;
'''


def poi_types(tags: dict) -> list[str]:
    """Preserve only requested feature kinds, not shops/roads with landmark names."""
    kinds = []
    if (tags.get("railway") == "station" or tags.get("public_transport") == "station") and (
        tags.get("station") == "subway" or tags.get("subway") == "yes"
    ):
        kinds.append("metro")
    if tags.get("natural") == "beach":
        kinds.append("beach")
    if tags.get("aeroway") == "aerodrome" and tags.get("iata") in {"DXB", "DWC"}:
        kinds.append(tags["iata"].lower())
    for pattern, kind in (
        (r"^(the )?dubai mall$", "dubai_mall"),
        (r"^burj khalifa$", "burj_khalifa"),
        (r"^(expo city( dubai)?|expo 2020( dubai)?)$", "expo_city"),
        (r"^dubai marina$", "dubai_marina"),
        (r"dubai museum|al fahidi|al shindagha|gold sou[qk]|spice sou[qk]|bastakiya", "old_dubai"),
    ):
        if any(re.search(pattern, tags.get(k, ""), re.I) for k in ("name", "name:en")):
            is_place = any(k in tags for k in ("place", "tourism", "historic", "building"))
            is_mall = tags.get("shop") == "mall"
            is_market = tags.get("amenity") == "marketplace"
            if (is_place or is_mall or is_market) and not tags.get("tourism") == "hotel":
                kinds.append(kind)
    return sorted(set(kinds))


def normalize(raw: dict, fetched_at: str, endpoint: str = ENDPOINT) -> tuple[dict, dict, dict]:
    if raw.get("remark"):
        raise ValueError(f"Overpass returned an incomplete result: {raw['remark']}")
    hotels, pois = {}, {}
    unnamed, invalid = 0, 0
    for element in raw["elements"]:
        tags = element.get("tags", {})
        position = element if "lat" in element else element.get("center", {})
        lat, lon = position.get("lat"), position.get("lon")
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            invalid += 1
            continue
        osm_type, osm_id = element["type"], element["id"]
        record = {
            "id": f"{osm_type}/{osm_id}",
            "osm_type": osm_type,
            "osm_id": osm_id,
            "name": (tags.get("name", "").strip() or tags.get("name:en", "").strip()),
            "name_en": tags.get("name:en"),
            "lat": lat,
            "lon": lon,
            "coordinate_method": "node" if osm_type == "node" else "osm_bbox_center",
            "website": tags.get("website") or tags.get("contact:website"),
        }
        if tags.get("tourism") == "hotel":
            if not record["name"]:
                unnamed += 1
                continue
            stars_tag = tags.get("stars")
            stars = int(stars_tag) if stars_tag in {"1", "2", "3", "4", "5"} else None
            hotels[record["id"]] = {
                **record,
                "stars": stars,
                "stars_tag": stars_tag,
                "stars_estimated": 3 if stars is None else None,
                "stars_estimation_method": "unknown_category_default_3_v1"
                if stars is None
                else None,
            }
        kinds = poi_types(tags)
        if kinds:
            pois[record["id"]] = {**record, "types": kinds, "iata": tags.get("iata")}
    if not hotels or not pois:
        raise ValueError("Empty hotels or POIs: refusing to overwrite a snapshot")
    before = dict(sorted(Counter(t for p in pois.values() for t in p["types"]).items()))
    pois = {p["id"]: p for p in dedupe_pois(list(pois.values()))}
    hotels = {h["id"]: h for h in enrich_hotels(list(hotels.values()), list(pois.values()))}
    metadata = {
        "fetched_at": fetched_at,
        "osm_base": raw.get("osm3s", {}).get("timestamp_osm_base"),
        "source": endpoint,
        "area": "Dubai emirate (ISO3166-2=AE-DU)",
        "licence": "ODbL-1.0",
        "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "attribution": "© OpenStreetMap contributors",
        "attribution_url": "https://www.openstreetmap.org/copyright",
        "query_sha256": hashlib.sha256(QUERY.encode()).hexdigest(),
    }
    counts = {
        "hotels_kept": len(hotels),
        "hotels_with_stars_tag": sum(h["stars_tag"] is not None for h in hotels.values()),
        "hotels_with_valid_stars": sum(h["stars"] is not None for h in hotels.values()),
        "hotels_without_name_dropped": unnamed,
        "elements_without_valid_coords": invalid,
        "pois_by_type": dict(sorted(Counter(t for p in pois.values() for t in p["types"]).items())),
    }
    return (
        {**metadata, "hotels": sorted(hotels.values(), key=lambda h: h["id"])},
        {**metadata, "pois": sorted(pois.values(), key=lambda p: p["id"])},
        {**metadata, "counts": counts, "poi_counts_before_dedupe": before},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "osm")
    args = parser.parse_args()
    request = Request(
        args.endpoint,
        data=urlencode({"data": QUERY}).encode(),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=210) as response:
            raw_bytes = response.read()
        raw = json.loads(raw_bytes)
        fetched_at = datetime.now(UTC).isoformat()
        hotels, pois, manifest = normalize(raw, fetched_at, args.endpoint)
        manifest["response_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        args.output.mkdir(parents=True, exist_ok=True)
        # Validate every payload before replacing any prior output.
        for filename, payload in (
            ("hotels.json", hotels),
            ("pois.json", pois),
            ("manifest.json", manifest),
        ):
            temporary = args.output / f"{filename}.tmp"
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            temporary.replace(args.output / filename)
        (args.output / "query.overpass").write_text(QUERY, encoding="utf-8")
        print(json.dumps(manifest["counts"], indent=2))
        return 0
    except (URLError, OSError, ValueError, KeyError) as error:
        print(f"Snapshot fetch failed; no synthetic substitute: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

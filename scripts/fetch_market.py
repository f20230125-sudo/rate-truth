"""Network reviewer: fetch all Xotelo list pages, rates, and optional SerpApi snapshots.

Run: python scripts/dev.py -m scripts.fetch_market [--provider xotelo|serpapi|all]
The default is all; SerpApi is skipped without its environment key.
"""

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Support direct script execution as well as python -m scripts.fetch_market.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.market.base import SERPAPI, XOTELO, MarketError, compact_property  # noqa: E402
from rate_truth.market.calibrate import write_calibration  # noqa: E402
from rate_truth.market.matching import match_many  # noqa: E402
from rate_truth.market.repository import MarketRepository  # noqa: E402
from rate_truth.market.serpapi import SerpApi, parse_property, properties_from  # noqa: E402
from rate_truth.market.storage import market_dir, write_json  # noqa: E402
from rate_truth.market.xotelo import Xotelo  # noqa: E402
from rate_truth.supplier.catalog import Catalog  # noqa: E402

QUERIES = [
    "hotels in Downtown Dubai",
    "Dubai Marina hotels",
    "Deira hotels",
    "Business Bay hotels",
    "JBR hotels",
    "Al Barsha hotels",
    "Bur Dubai hotels",
    "Palm Jumeirah hotels",
    "Jumeirah hotels",
    "Dubai Airport hotels",
    "Al Jaddaf hotels",
    "Sheikh Zayed Road hotels",
]


def stay_dates(today):
    def next_weekday(weekday):
        return today + timedelta(days=(weekday - today.weekday()) % 7 or 7)

    return [next_weekday(2), next_weekday(5), today + timedelta(days=30)]


def fetch_snapshot(
    *,
    root=None,
    today=None,
    provider="all",
    refresh=None,
    max_hotels=None,
    catalog=None,
    xotelo=None,
    serpapi=None,
    calibration_path=None,
):
    root = root or market_dir()
    today = today or datetime.now(UTC).date()
    catalog = catalog or Catalog()
    repository = MarketRepository(root)
    xotelo, serpapi = xotelo or Xotelo(root), serpapi or SerpApi()
    matches = repository.matches()
    observations, searches, errors = [], [], []
    counts = {"searched": 0, "properties_seen": 0, "matched_to_osm": 0, "ambiguous_dropped": 0}

    def error(exc, label, query):
        errors.append({"provider": label, "query": query, "code": exc.code, "message": str(exc)})

    def record_search(label, query, params, fetched_at, records):
        searches.append(
            {
                "provider": label,
                "query": query,
                "params": params,
                "fetched_at": fetched_at,
                "matched_results": [
                    {k: v for k, v in r.items() if k != "property"}
                    for r in records
                    if r["status"] == "matched"
                ],
            }
        )
        counts["searched"] += 1
        counts["properties_seen"] += len(records)
        counts["matched_to_osm"] += sum(r["status"] == "matched" for r in records)
        counts["ambiguous_dropped"] += sum(r["status"] == "ambiguous" for r in records)

    def save_match(row, label):
        matches.setdefault(row["hotel_id"], {})[label] = {
            "property": compact_property(row["property"]),
            "match_score": row["score"],
            "distance_m": row["distance_m"],
        }

    def get_observation(hotel_id, label, entry, day):
        client = xotelo if label == XOTELO else serpapi
        try:
            obs = client.observe(entry["property"], day, day + timedelta(days=1))
            if obs:
                # Live detail names/coordinates may change; enforce identity again.
                identity = match_many(
                    [
                        {
                            "name": obs.name,
                            "gps_coordinates": {"latitude": obs.lat, "longitude": obs.lon},
                        }
                    ],
                    catalog.hotels.values(),
                )[0]
                if identity.get("hotel_id") != hotel_id:
                    raise MarketError("market_match_changed", "refreshed identity did not match")
                observations.append(
                    {
                        "hotel_id": hotel_id,
                        "match_score": identity["score"],
                        "distance_m": identity["distance_m"],
                        "observation": obs.output(),
                    }
                )
            record_search(
                label,
                entry["property"]["name"],
                {
                    "checkin": day.isoformat(),
                    "checkout": (day + timedelta(days=1)).isoformat(),
                    "adults": 2,
                },
                obs.fetched_at if obs else datetime.now(UTC).isoformat(),
                [],
            )
        except MarketError as exc:
            error(exc, label, entry["property"]["name"])

    if refresh is not None:
        latest = {}
        for row in repository.records():
            latest[row["hotel_id"]] = max(
                latest.get(row["hotel_id"], ""), row["observation"]["fetched_at"]
            )
        selected = sorted(matches, key=lambda k: (latest.get(k, ""), k))[:refresh]
        for hotel_id in selected:
            for label, entry in matches[hotel_id].items():
                if (
                    provider == "xotelo"
                    and label != XOTELO
                    or provider == "serpapi"
                    and label != SERPAPI
                ):
                    continue
                if label == SERPAPI and not serpapi.enabled:
                    continue
                get_observation(hotel_id, label, entry, today + timedelta(days=1))
    else:
        if provider in {"all", "xotelo"}:
            # Rebuild A's index from the full list; discard identities no longer matched.
            for hotel_id in list(matches):
                matches[hotel_id].pop(XOTELO, None)
                if not matches[hotel_id]:
                    del matches[hotel_id]
            pages = xotelo.list_all()
            properties = [p for page in pages for p in page["response"]["result"]["list"]]
            records = match_many(properties, catalog.hotels.values())
            for page in pages:
                keys = {p["key"] for p in page["response"]["result"]["list"]}
                record_search(
                    XOTELO,
                    "Dubai hotel list",
                    {"url": page["url"]},
                    page["fetched_at"],
                    [r for r in records if r["property"]["key"] in keys],
                )
            for row in records:
                if row["status"] == "matched":
                    save_match(row, XOTELO)
            # Persist the complete list index even when rate fetches are interrupted.
            write_json(root / "matches.json", matches)
            selected = sorted(k for k in matches if XOTELO in matches[k])
            if max_hotels is not None:
                selected = selected[:max_hotels]
            for hotel_id in selected:
                for day in stay_dates(today):
                    get_observation(hotel_id, XOTELO, matches[hotel_id][XOTELO], day)
        if provider in {"all", "serpapi"} and serpapi.enabled:
            exhausted = False
            for query in QUERIES:
                if exhausted:
                    break
                for day in stay_dates(today):
                    token = None
                    for _ in range(2):  # Never more than one pagination request per planned search.
                        try:
                            saved = serpapi.search(
                                query, day, day + timedelta(days=1), next_page_token=token
                            )
                        except MarketError as exc:
                            error(exc, SERPAPI, query)
                            exhausted = exc.code in {
                                "market_budget_exhausted",
                                "market_budget_unavailable",
                            }
                            break
                        records = match_many(
                            properties_from(saved["response"]), catalog.hotels.values()
                        )
                        record_search(SERPAPI, query, saved["params"], saved["fetched_at"], records)
                        for row in records:
                            if row["status"] != "matched":
                                continue
                            save_match(row, SERPAPI)
                            obs = parse_property(
                                row["property"],
                                day,
                                day + timedelta(days=1),
                                saved["fetched_at"],
                                query,
                            )
                            if obs:
                                observations.append(
                                    {
                                        "hotel_id": row["hotel_id"],
                                        "match_score": row["score"],
                                        "distance_m": row["distance_m"],
                                        "observation": obs.output(),
                                    }
                                )
                        token = (saved["response"].get("serpapi_pagination") or {}).get(
                            "next_page_token"
                        )
                        if not token:
                            break
                    if exhausted:
                        break
    write_json(root / "matches.json", matches)
    # Preserve earlier same-day observations during --refresh and partial reruns.
    path = root / f"snapshot-{today.isoformat()}.json"
    from rate_truth.market.storage import read_json

    previous = read_json(path, {}).get("observations", [])
    payload = {
        "schema_version": 1,
        "snapshot_date": today.isoformat(),
        "fetched_at": datetime.now(UTC).isoformat(),
        "searches": searches,
        "observations": previous + observations,
        "manifest": {
            **counts,
            "matched_hotels": len(matches),
            "observations": len(observations),
            "serpapi_enabled": serpapi.enabled,
            "budget": serpapi.budget.status(),
        },
        "errors": errors,
        "disclosure": "observed price, not a quote",
    }
    write_json(path, payload)
    write_calibration(repository.records(), calibration_path)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("all", "xotelo", "serpapi"), default="all")
    parser.add_argument("--refresh", type=int, metavar="N")
    parser.add_argument(
        "--max-hotels",
        type=int,
        help="limit rate fetching only; list pagination is always complete",
    )
    parser.add_argument(
        "--today", type=date.fromisoformat, help="fixed snapshot plan date YYYY-MM-DD"
    )
    args = parser.parse_args()
    if (
        args.refresh is not None
        and args.refresh < 1
        or args.max_hotels is not None
        and args.max_hotels < 1
    ):
        parser.error("counts must be positive")
    try:
        result = fetch_snapshot(
            provider=args.provider,
            refresh=args.refresh,
            max_hotels=args.max_hotels,
            today=args.today,
        )
    except MarketError as exc:
        parser.exit(1, f"{exc.code}: {exc}\n")
    import json

    print(json.dumps(result["manifest"], indent=2))
    if result["errors"]:
        print(json.dumps({"errors": result["errors"]}, indent=2))


if __name__ == "__main__":
    main()

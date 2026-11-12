"""Rebuild Xotelo identities and a rate-fetch plan without any network access."""

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from rate_truth.market.base import XOTELO
from rate_truth.market.matching import match_many, tokens
from rate_truth.market.storage import read_json, write_json
from rate_truth.supplier.catalog import Catalog
from scripts.fetch_market import stay_dates


def rebuild(root, residue, today):
    hotels = Catalog().hotels
    properties, rates = {}, {}
    paths = sorted((root / "cache").glob("*.json"))
    for path in paths:
        saved = read_json(path)
        result = saved.get("response", {}).get("result") or {}
        for prop in result.get("list", []):
            properties[prop["key"]] = prop
        query = parse_qs(urlsplit(saved.get("url", "")).query)
        if "hotel_key" in query and result.get("rates"):
            rates[(query["hotel_key"][0], query["chk_in"][0], query["chk_out"][0])] = saved
    if not properties:
        raise ValueError("No cached list pages; refusing to overwrite matches")
    records = match_many(properties.values(), hotels.values())
    matches, lines, pending = {}, [], {}
    with_rates = set()
    for row in records:
        if row["status"] != "matched":
            continue
        prop, hid = row["property"], row["hotel_id"]
        matches[hid] = {
            XOTELO: {
                "property": {k: prop[k] for k in ("key", "name", "geo")},
                "match_score": row["score"],
                "distance_m": row["distance_m"],
            }
        }
        if tokens(hotels[hid].name) != tokens(prop["name"]):
            lines.append(
                f"{hid}\t{hotels[hid].name}\t{prop['key']}\t{prop['name']}"
                f"\tscore={row['score']}\tdistance_m={row['distance_m']}"
            )
        if any(key[0] == prop["key"] for key in rates):
            with_rates.add(hid)
        missing = []
        for day in stay_dates(today):
            from datetime import timedelta

            key = (prop["key"], day.isoformat(), (day + timedelta(days=1)).isoformat())
            if key not in rates:
                missing.append(key[1])
        if missing:
            pending[hid] = missing
    write_json(root / "matches.json", matches)
    residue.parent.mkdir(parents=True, exist_ok=True)
    residue.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    report = {
        "offline": True,
        "cache_files_preserved": len(paths),
        "properties": len(properties),
        "statuses": dict(Counter(r["status"] for r in records)),
        "matched_hotels": len(matches),
        "residue_rows": len(lines),
        "matched_hotels_with_any_cached_rates": len(with_rates),
        "matched_hotels_without_cached_rates": len(matches) - len(with_rates),
        "plan_date": today.isoformat(),
        "hotels_needing_planned_rate_fetches": len(pending),
        "planned_rate_fetches_missing": sum(map(len, pending.values())),
        "missing_stays": pending,
    }
    write_json(residue.with_suffix(".json"), report)
    return {k: v for k, v in report.items() if k != "missing_stays"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/market"))
    parser.add_argument("--residue", type=Path, default=Path(".local/match-residue.txt"))
    parser.add_argument("--today", type=date.fromisoformat, default=date(2026, 11, 11))
    args = parser.parse_args()
    print(json.dumps(rebuild(args.root, args.residue, args.today), indent=2))

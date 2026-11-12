"""Thirty rule-derived relevance sets. No expected IDs are selected by either retriever."""

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.rag.bm25 import BM25
from rate_truth.rag.cards import Cards
from rate_truth.rag.retrieve import Retriever
from rate_truth.settings import ROOT
from rate_truth.supplier.catalog import Catalog


def queries(records):
    result = []
    # Geometry, tagged class, proximity area, and star-unknown conditions are independent
    # of all lexical/semantic scores. Keep empty relevance sets out of recall denominators.
    for area in ("Dubai Marina", "Downtown Dubai", "Old Dubai", "Airport", "Expo City", None):
        for kind, bound in (
            ("metro", 300),
            ("metro", 800),
            ("metro", 1500),
            ("beach", 1000),
            ("beach", 3000),
            ("stars", 4),
            ("stars", None),
        ):
            ids = []
            for identifier, record in records.items():
                h = record["hotel"]
                if area and h["area"] != "near " + area:
                    continue
                place = h.get("nearest_" + kind)
                relevant = (
                    h["stars"] == bound if kind == "stars" else place and place["metres"] <= bound
                )
                if relevant:
                    ids.append(identifier)
            if not ids:
                continue
            text = (
                f"Hotels with OSM stars {bound}"
                if kind == "stars" and bound
                else "Hotels without a tagged OSM star rating"
                if kind == "stars"
                else f"{kind.title()} proximity: within {bound} metres straight-line"
            )
            text += f" near {area}" if area else " in Dubai"
            result.append(
                {
                    "id": f"r{len(result) + 1:02}",
                    "query": text,
                    "rule": {"near_area": area, "kind": kind, "bound": bound},
                    "expected_hotel_ids": sorted(ids),
                    "expected_card_ids": [f"osm:{i}" for i in sorted(ids)],
                }
            )
    return result[:30]


def metrics(returned, relevant):
    """Binary relevance; absent returned positions count as nonrelevant."""
    relevant = set(relevant)
    hits = len(relevant.intersection(returned[:5]))
    dcg = sum(1 / math.log2(rank + 2) for rank, key in enumerate(returned[:10]) if key in relevant)
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(10, len(relevant))))
    return {
        "hit_at_5": float(hits > 0),
        "precision_at_5": hits / 5,
        "r_precision": len(relevant.intersection(returned[: len(relevant)])) / len(relevant),
        "ndcg_at_10": dcg / ideal,
    }


def main():
    records = Cards(Catalog()).records
    cases = queries(records)
    assert len(cases) == 30
    lexical, hybrid = BM25(records), Retriever(records)
    report = {
        "n": 30,
        "retrieval_mode": hybrid.mode,
        "definition": "Macro binary hit@5 (any relevant), precision@5 (hits/5), "
        "R-precision (precision and recall at k=|relevant|), and nDCG@10. "
        "Nonempty relevance sets are independent of ranking. Queries refer to explicit card "
        "facts; numeric metro constraints in agent requests use search_hotels.near_metro. "
        "Distances are straight-line, not walking routes.",
        "queries": [],
    }
    for case in cases:
        expected = set(case["expected_hotel_ids"])
        row = {**case}
        for mode, index in (("bm25", lexical), ("hybrid", hybrid)):
            returned = [
                r["hotel"]["id"] for r in index.search(case["query"], max(10, len(expected)))
            ]
            row[mode] = {
                "ids": returned,
                **metrics(returned, expected),
            }
        report["queries"].append(row)
    for mode in ("bm25", "hybrid"):
        for metric in ("hit_at_5", "precision_at_5", "r_precision", "ndcg_at_10"):
            report[f"{mode}_{metric}"] = (
                sum(q[mode][metric] for q in report["queries"]) / len(cases)
                if mode == "bm25" or hybrid.mode == "hybrid"
                else None
            )
    path = ROOT / "eval/results.json"
    results = json.loads(path.read_text()) if path.exists() else {"run_at": None}
    results["retrieval"] = report
    results["retrieval_run_at"] = datetime.now(UTC).isoformat()
    results["agent"] = {
        "run_at": None,
        "reason": "Live LLM recordings pending network-enabled reviewer run",
    }
    path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    (ROOT / "eval/retrieval_queries.json").write_text(
        json.dumps(cases, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "queries"}))


if __name__ == "__main__":
    main()

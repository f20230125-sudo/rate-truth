"""Idempotent offline normalization of the fetched OSM snapshot."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.geo import counts, dedupe_pois, enrich_hotels  # noqa: E402
from rate_truth.settings import DATA  # noqa: E402


def main():
    folder = DATA / "osm"
    docs = {
        name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("hotels", "pois", "manifest")
    }
    before = counts(docs["pois"]["pois"])
    docs["pois"]["pois"] = dedupe_pois(docs["pois"]["pois"])
    docs["hotels"]["hotels"] = enrich_hotels(docs["hotels"]["hotels"], docs["pois"]["pois"])
    after = counts(docs["pois"]["pois"])
    manifest = docs["manifest"]
    manifest.setdefault("poi_counts_before_dedupe", before)
    manifest["counts"]["pois_by_type"] = after
    manifest["normalization"] = {
        "poi_dedupe": "NFKC casefold compact word names (name or name_en), same types, <=400m; "
        "prefer node, then stable OSM ID; compare to canonical point",
        "area": "Nearest selected landmark <=2000m; fixed AREA_NAMES mapping in rate_truth/geo.py; "
        "otherwise null. DWC is not mapped to Airport.",
    }
    for name, doc in docs.items():
        (folder / f"{name}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({"before": manifest["poi_counts_before_dedupe"], "after": after}))


if __name__ == "__main__":
    main()

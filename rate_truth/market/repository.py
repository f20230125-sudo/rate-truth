"""Read recorded observations without inventing a fallback market snapshot."""

from rate_truth.market.storage import market_dir, read_json, write_json
from rate_truth.settings import DATA


class MarketRepository:
    def __init__(self, root=None):
        self.root = root or market_dir()
        self.seed = DATA / "market" if root is None else self.root

    def records(self):
        records = []
        paths = set(self.root.glob("snapshot-*.json")) | set(self.seed.glob("snapshot-*.json"))
        for path in sorted(paths):
            records.extend(read_json(path, {}).get("observations", []))
        records.extend(read_json(self.root / "live.json", {}).get("observations", []))
        latest = {}
        for row in records:
            o = row.get("observation")
            if not o or not row.get("hotel_id"):
                continue
            key = (row["hotel_id"], o["provider"], o["checkin"], o["checkout"])
            if key not in latest or o["fetched_at"] > latest[key]["observation"]["fetched_at"]:
                latest[key] = row
        return list(latest.values())

    def matches(self):
        return read_json(self.root / "matches.json", None) or read_json(
            self.seed / "matches.json", {}
        )

    def save_live(self, row):
        # Keep one latest observation per provider/hotel/stay; bound file growth.
        from rate_truth.market.storage import file_lock

        with file_lock(self.root / "live.lock"):
            records = read_json(self.root / "live.json", {}).get("observations", [])
            o = row["observation"]
            records = [
                r
                for r in records
                if not (
                    r["hotel_id"] == row["hotel_id"]
                    and all(
                        r["observation"][k] == o[k] for k in ("provider", "checkin", "checkout")
                    )
                )
            ]
            records.append(row)
            records.sort(key=lambda r: r["observation"]["fetched_at"], reverse=True)
            write_json(self.root / "live.json", {"observations": records[:10000]})

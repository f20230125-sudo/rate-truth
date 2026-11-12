"""Read only the local OSM snapshot; names remain untrusted data."""

import json
from pathlib import Path

from rate_truth.settings import DATA
from rate_truth.supplier.models import Hotel


class Catalog:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA / "osm" / "hotels.json"
        self._hotels: dict[str, Hotel] | None = None

    @property
    def hotels(self) -> dict[str, Hotel]:
        if self._hotels is None:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._hotels = {h["id"]: Hotel.model_validate(h) for h in payload["hotels"]}
        return self._hotels

    def get(self, hotel_id: str) -> Hotel:
        try:
            return self.hotels[hotel_id]
        except KeyError:
            raise ValueError("unknown hotel id") from None

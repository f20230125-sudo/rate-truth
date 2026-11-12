"""Facts only: OSM fields and distances to snapshot POIs, each with a source."""

import json
from functools import cached_property

from rate_truth.geo import UNKNOWN_STARS, distance, normalized_name
from rate_truth.hotel_groups import hotel_groups
from rate_truth.settings import DATA
from rate_truth.supplier.catalog import Catalog


class Cards:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog

    @cached_property
    def observations(self):
        from rate_truth.market.repository import MarketRepository

        return MarketRepository().records()

    @cached_property
    def pois(self):
        return json.loads((DATA / "osm/pois.json").read_text(encoding="utf-8"))["pois"]

    @cached_property
    def mapped_ids(self):
        return hotel_groups(self.catalog.hotels.values())

    @cached_property
    def records(self):
        return {h.id: self.build(h) for h in self.catalog.hotels.values()}

    def build(self, hotel):
        source = f"https://www.openstreetmap.org/{hotel.id}"
        position = hotel.model_dump()
        facts = [
            {"text": hotel.name, "source": source},
            {"text": f"OSM coordinates: {hotel.lat}, {hotel.lon}", "source": source},
            {
                "text": f"OSM stars tag: {hotel.stars}" if hotel.stars else UNKNOWN_STARS,
                "source": source,
            },
        ]
        if hotel.website:
            facts.append({"text": f"Website: {hotel.website}", "source": source})
        if hotel.area:
            facts.append(
                {
                    "text": f"Proximity: near {hotel.area}; selected landmark within 2 km",
                    "source": hotel.area_source,
                }
            )

        for row in self.observations:
            if row["hotel_id"] != hotel.id:
                continue
            observation = row["observation"]
            facts.append(
                {
                    "text": f"Market observation: {observation['provider']}; "
                    f"fetched_at {observation['fetched_at']}; "
                    f"stay {observation['checkin']} to {observation['checkout']}; "
                    f"AED {observation['amount_aed']} per night; "
                    f"{observation['tax_label']}; observed price, not a quote",
                    "source": observation.get("link")
                    or (
                        "https://xotelo.com"
                        if "Xotelo" in observation["provider"]
                        else "https://serpapi.com/google-hotels-api"
                    ),
                }
            )

        def nearby(pois):
            return sorted(pois, key=lambda p: (distance(position, p), p["id"]))

        def item(poi, kind=None):
            metres = round(distance(position, poi))
            name = (
                poi.get("name_en")
                or poi["name"]
                or ("unnamed beach (OSM)" if "beach" in poi["types"] else "unnamed landmark (OSM)")
            )
            facts.append(
                {
                    "text": f"{kind + ': ' if kind else ''}{name}: {metres} metres "
                    "straight-line from hotel",
                    "source": "https://www.openstreetmap.org/" + poi["id"],
                }
            )
            bounds = {"metro": (300, 800, 1500), "beach": (1000, 3000)}
            for bound in bounds.get(kind, ()):
                if metres <= bound:
                    facts.append(
                        {
                            "text": f"{kind.title()} proximity: within {bound} metres "
                            "straight-line; computed from OSM coordinates, not a walking route",
                            "source": "https://www.openstreetmap.org/" + poi["id"],
                        }
                    )
            return {"name": name, "metres": metres}

        metros = nearby([p for p in self.pois if "metro" in p["types"]])
        beaches = nearby([p for p in self.pois if "beach" in p["types"]])
        named_beaches = [p for p in beaches if p.get("name_en") or p.get("name")]
        beaches = named_beaches or beaches
        landmarks = nearby([p for p in self.pois if set(p["types"]) - {"metro", "beach"}])
        unique = {}
        for p in landmarks:
            key = (normalized_name(p.get("name_en") or p["name"]), tuple(sorted(p["types"])))
            unique.setdefault(key, p)
        landmarks = list(unique.values())
        osm_type, osm_id = hotel.id.split("/")
        result = {
            "id": hotel.id,
            "osm_id": osm_id,
            "osm_type": osm_type,
            "name": hotel.name,
            "name_en": hotel.name_en,
            "mapped_osm_ids": self.mapped_ids[hotel.id],
            "lat": hotel.lat,
            "lon": hotel.lon,
            "area": f"near {hotel.area}" if hotel.area else None,
            "stars": hotel.stars,
            "stars_estimated": 3 if hotel.stars is None else None,
            "stars_method": UNKNOWN_STARS if hotel.stars is None else None,
            "website": hotel.website,
            "nearest_metro": item(metros[0], "metro") if metros else None,
            "nearest_beach": item(beaches[0], "beach") if beaches else None,
            "landmarks": [item(p) for p in landmarks],
        }
        return {"hotel": result, "card": {"id": f"osm:{hotel.id}", "facts": facts}}

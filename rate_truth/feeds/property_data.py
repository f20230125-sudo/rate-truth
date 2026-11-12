"""Synthetic room capacities and plan terms, explicitly separated from OSM facts."""

from rate_truth.feeds.common import Feed, element, transaction_root
from rate_truth.geo import UNKNOWN_STARS
from rate_truth.supplier.models import CAPACITY, Plan


def localized(parent, tag, text):
    element(element(parent, tag), "Text", language="en", text=text)


def build(hotels):
    root = transaction_root()
    for hotel in hotels:
        prop = element(root, "PropertyDataSet", action="overlay")
        element(prop, "Property", hotel.id)
        for room, capacity in CAPACITY.items():
            data = element(prop, "RoomData")
            element(data, "RoomID", room.value)
            localized(data, "Name", f"Synthetic {room.value} room")
            description = "Simulated room; capacity is not an observed hotel amenity."
            if hotel.stars is None:
                description += " " + UNKNOWN_STARS
            localized(data, "Description", description)
            element(data, "Capacity", capacity)
        for plan in Plan:
            data = element(prop, "PackageData")
            element(data, "PackageID", plan.value)
            localized(data, "Name", f"Synthetic {plan.value} plan")
            element(
                data,
                "Refundable",
                available=str(not plan.value.startswith("non_")).lower(),
                **(
                    {"refundable_until_days": "1", "refundable_until_time": "18:00:00"}
                    if not plan.value.startswith("non_")
                    else {}
                ),
            )
            element(data, "BreakfastIncluded", str(plan.value.endswith("breakfast")).lower())
    return Feed.create("property_data", root)

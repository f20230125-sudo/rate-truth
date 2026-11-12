"""Conservative display grouping; every supplier identity remains addressable."""

import unicodedata

from rate_truth.geo import distance, normalized_name


def has_latin_name(hotel):
    return bool(hotel.name_en) or any(
        "LATIN" in unicodedata.name(c, "") for c in hotel.name
    )


def display_order(hotel):
    return (
        0 if hotel.stars is not None else 1 if has_latin_name(hotel) else 2,
        -(hotel.stars or 0),
        (hotel.name_en or hotel.name).strip().casefold(),
        hotel.id,
    )


def hotel_groups(hotels):
    groups = {}
    by_name = {}
    for hotel in sorted(hotels, key=display_order):
        key = normalized_name(hotel.name)
        candidates = by_name.setdefault(key, [])
        group = next(
            (
                members for members in candidates
                if key and all(
                    distance(hotel.model_dump(), member.model_dump()) <= 150
                    for member in members
                )
            ),
            None,
        )
        if group is None:
            group = []
            candidates.append(group)
        group.append(hotel)
        groups[hotel.id] = group
    return {identifier: [h.id for h in members] for identifier, members in groups.items()}

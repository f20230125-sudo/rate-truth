"""Hotel identities and geocodes only. The snapshot contains no street addresses."""

from lxml import etree

from rate_truth.feeds.common import Feed, element
from rate_truth.geo import UNKNOWN_STARS


def build(hotels):
    root = etree.Element("listings", nsmap={"xsi": "http://www.w3.org/2001/XMLSchema-instance"})
    root.set(
        "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation",
        "https://www.gstatic.com/localfeed/local_feed.xsd",
    )
    element(root, "language", "en")
    element(root, "datum", "WGS84")
    for hotel in hotels:
        listing = element(root, "listing")
        element(listing, "id", hotel.id)
        element(listing, "name", hotel.name)
        element(listing, "country", "AE")
        element(listing, "latitude", hotel.lat)
        element(listing, "longitude", hotel.lon)
        # No invented address or rating. A comment discloses our pricing fallback.
        if hotel.stars is None:
            listing.append(etree.Comment(UNKNOWN_STARS))
    return Feed.create("hotel_list", root)

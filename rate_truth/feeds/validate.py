"""No silent skips and no network/entity resolution, including schema dependencies."""

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lxml import etree

from rate_truth.feeds.common import OTA

XSD_DIR = Path(__file__).parent / "xsd"
SCHEMAS = {
    "hotel_list": "local_feed.xsd",
    "property_data": "transaction_property_data.xsd",
    "transaction": "transaction.xsd",
    "query": "query.xsd",
}
SCHEMA_URLS = {
    "hotel_list": "https://www.gstatic.com/localfeed/local_feed.xsd",
    **{
        kind: "https://www.gstatic.com/ads-travel/hotels/api/" + name
        for kind, name in SCHEMAS.items()
        if kind != "hotel_list"
    },
}
ARI_ROOTS = {
    "ari_rate": "OTA_HotelRateAmountNotifRQ",
    "ari_avail": "OTA_HotelAvailNotifRQ",
    "ari_inv": "OTA_HotelInvCountNotifRQ",
}
MISSING = "Missing Google XSDs; run python scripts/dev.py scripts/fetch_xsd.py with network access"


class LocalSchemas(etree.Resolver):
    def __init__(self, folder):
        self.folder = folder

    def resolve(self, url, pubid, context):
        name = url.replace("\\", "/").rsplit("/", 1)[-1]
        path = self.folder / name
        if not name.endswith(".xsd") or not path.is_file():
            raise FileNotFoundError(f"{MISSING}: {name}")
        return self.resolve_filename(str(path.resolve()), context)


def parse(xml):
    raw = xml.encode() if isinstance(xml, str) else xml
    if len(raw) > 2_000_000:
        raise ValueError("XML exceeds 2 MB")
    doc = etree.fromstring(
        raw,
        etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False),
    )
    if doc.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in doc.iter()):
        raise ValueError("DTD and entities are not allowed")
    return doc


def schema(kind, folder=None):
    folder = folder or XSD_DIR
    if kind not in SCHEMAS:
        raise ValueError("Unknown schema kind")
    if any(not (folder / name).is_file() for name in SCHEMAS.values()):
        raise FileNotFoundError(MISSING)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    parser.resolvers.add(LocalSchemas(folder))
    return etree.XMLSchema(etree.parse(str((folder / SCHEMAS[kind]).resolve()), parser))


def structural(doc, kind):
    """Validate the supported per-date Overlay profile, from Google's ARI references."""
    ns = {"o": OTA}
    if doc.tag != f"{{{OTA}}}{ARI_ROOTS[kind]}":
        raise ValueError("Unexpected ARI root/namespace")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", doc.get("EchoToken", "")):
        raise ValueError("EchoToken is required")
    if datetime.fromisoformat(doc.get("TimeStamp", "")).tzinfo is None:
        raise ValueError("TimeStamp must have an offset")
    if doc.get("Version") != "3.0":
        raise ValueError("Version must be 3.0")
    parent, child = {
        "ari_rate": ("RateAmountMessages", "RateAmountMessage"),
        "ari_avail": ("AvailStatusMessages", "AvailStatusMessage"),
        "ari_inv": ("Inventories", "Inventory"),
    }[kind]
    groups = doc.findall(f"o:{parent}", ns)
    if len(groups) != 1 or not groups[0].get("HotelCode"):
        raise ValueError("One property container with HotelCode is required")
    messages = groups[0].findall(f"o:{child}", ns)
    if not messages:
        raise ValueError("ARI messages must not be empty")
    for message in messages:
        controls = message.findall("o:StatusApplicationControl", ns)
        if len(controls) != 1:
            raise ValueError("One StatusApplicationControl required")
        c = controls[0]
        if date.fromisoformat(c.get("End", "")) < date.fromisoformat(c.get("Start", "")):
            raise ValueError("End precedes Start")
        if not c.get("InvTypeCode") or (kind != "ari_inv" and not c.get("RatePlanCode")):
            raise ValueError("Room and rate-plan identifiers required")
        if kind == "ari_rate":
            if doc.get("NotifType") != "Overlay":
                raise ValueError("Only Overlay rate profile supported")
            amounts = message.findall("o:Rates/o:Rate/o:BaseByGuestAmts/o:BaseByGuestAmt", ns)
            if len(amounts) != 1:
                raise ValueError("Exactly one occupancy amount required")
            amount = amounts[0]
            if (
                amount.get("CurrencyCode") != "AED"
                or not 1 <= int(amount.get("NumberOfGuests")) <= 8
            ):
                raise ValueError("Invalid currency/occupancy")
            for attr in ("AmountBeforeTax", "AmountAfterTax"):
                value = amount.get(attr, "")
                if not re.fullmatch(r"\d+\.\d{2}", value) or Decimal(value) < 0:
                    raise ValueError("Invalid amount")
            if Decimal(amount.get("AmountAfterTax")) < Decimal(amount.get("AmountBeforeTax")):
                raise ValueError("After-tax amount below base")
        elif kind == "ari_avail":
            r = message.find("o:RestrictionStatus", ns)
            if (
                r is None
                or r.get("Status") not in {"Open", "Close"}
                or r.get("Restriction") != "Master"
            ):
                raise ValueError("Invalid Master restriction")
        else:
            counts = message.findall("o:InvCounts/o:InvCount", ns)
            if len(counts) != 1 or counts[0].get("CountType") != "2":
                raise ValueError("CountType=2 required")
            if not re.fullmatch(r"\d+", counts[0].get("Count", "")):
                raise ValueError("Nonnegative integer count required")


def validate(xml, kind):
    check = "structural" if kind in ARI_ROOTS else "xsd"
    errors = []
    try:
        doc = parse(xml)
        if check == "structural":
            structural(doc, kind)
        else:
            validator = schema(kind)
            if not validator.validate(doc):
                errors = [
                    {"line": e.line or None, "message": e.message} for e in validator.error_log
                ]
    except (ValueError, TypeError, FileNotFoundError, etree.LxmlError) as exc:
        errors = [{"line": None, "message": str(exc)}]
    fetched = XSD_DIR / "FETCHED_AT"
    return {
        "valid": not errors,
        "check": check,
        "errors": errors,
        "schema_url": SCHEMA_URLS.get(kind),
        "xsd_fetched_at": fetched.read_text().strip() if fetched.exists() else None,
    }

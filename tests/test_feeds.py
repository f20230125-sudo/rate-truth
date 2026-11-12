import io
import json
import runpy
from datetime import timedelta
from pathlib import Path

import pytest
from lxml import etree

from rate_truth.feeds import ari, hotel_list, property_data, transaction
from rate_truth.feeds.validate import MISSING, SCHEMAS, XSD_DIR, parse, schema, validate
from rate_truth.settings import ROOT
from rate_truth.supplier.models import Plan, RoomType, StayRequest, dubai_today
from rate_truth.supplier.rates import RateEngine


@pytest.mark.parametrize("kind", list(SCHEMAS))
def test_cached_google_schemas_exist_and_compile(kind):
    # Deliberately FAIL, never skip when schema files/dependencies have not been fetched.
    try:
        assert schema(kind) is not None
    except (FileNotFoundError, etree.LxmlError) as exc:
        pytest.fail(f"{MISSING}: {exc}")


def test_missing_schema_fails_explicitly(tmp_path):
    with pytest.raises(FileNotFoundError, match="scripts/fetch_xsd.py"):
        schema("hotel_list", tmp_path)


def test_full_snapshot_hotel_list_and_property_data_xsd():
    hotels = list(RateEngine().catalog.hotels.values())
    for artifact in (hotel_list.build(hotels), property_data.build(hotels)):
        result = artifact.output()
        assert result["valid"], result["errors"]
        assert result["check"] == "xsd" and result["schema_url"]
    assert len(parse(hotel_list.build(hotels).xml).findall("listing")) == 737


@pytest.mark.parametrize("day", ["2026-12-14", "2027-04-14", "2027-08-11"])
def test_full_snapshot_pull_prices_xsd_and_trace(day):
    engine = RateEngine()
    artifact = transaction.build(
        engine,
        [StayRequest(hotel_id=h.id, checkin=day, nights=3) for h in engine.catalog.hotels.values()],
    )
    result = artifact.output()
    assert result["valid"], result["errors"]
    for parsed, f in zip(transaction.prices(artifact), artifact.folios, strict=True):
        assert parsed["total"] == f["total"]
        assert parsed["rate_id"] == f["rate_id"]
        assert parsed["computed_at"] == f["computed_at"]


@pytest.mark.parametrize("plan", list(Plan))
@pytest.mark.parametrize("room", list(RoomType))
def test_all_generated_feed_types(engine, hotel, plan, room):
    stay = StayRequest(
        hotel_id=hotel.id, checkin=dubai_today(), nights=3, guests=2, room_type=room, plan=plan
    )
    feeds = [
        hotel_list.build([hotel]),
        property_data.build([hotel]),
        transaction.build(engine, [stay]),
        *ari.build(engine, stay),
    ]
    for feed in feeds:
        result = feed.output()
        assert result["valid"], (feed.kind, result["errors"])
        if feed.kind.startswith("ari_"):
            assert result["check"] == "structural" and result["schema_url"] is None
    # Per-date ARI uses one-night prices; never silently average a discounted LOS price.
    for f in feeds[3].folios:
        assert f["nights"] == 1 and f["rate_id"] and f["computed_at"]


def test_untrusted_names_are_xml_data_and_unknown_stars_disclosed(hotel):
    hotel = hotel.model_copy(update={"stars": None})
    feed = hotel_list.build([hotel])
    assert parse(feed.xml).findtext("listing/name") == hotel.name
    assert b"&lt;script&gt;" in feed.xml and b"<script>" not in feed.xml
    assert b"stars not tagged in OSM; priced as 3-star" in feed.xml
    assert validate(property_data.build([hotel]).xml, "property_data")["valid"]


def test_ari_occupied_nights_can_extend_past_checkin_horizon(engine, hotel):
    stay = StayRequest(hotel_id=hotel.id, checkin=dubai_today() + timedelta(days=365), nights=30)
    for feed in ari.build(engine, stay):
        assert feed.output()["valid"]


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><x>&a;</x>',
        '<!DOCTYPE x SYSTEM "https://attacker.invalid/xxe"><x/>',
        "<listings><language>en</language></listings>",
        "<wrong/>",
        "<x>",
    ],
)
def test_bad_and_entity_xml_rejected(xml):
    result = validate(xml, "hotel_list")
    assert not result["valid"] and result["errors"]


@pytest.mark.parametrize(
    ("kind", "path", "attribute", "value"),
    [
        ("ari_rate", ".//{*}BaseByGuestAmt", "CurrencyCode", "USD"),
        ("ari_rate", ".//{*}BaseByGuestAmt", "AmountAfterTax", "NaN"),
        ("ari_rate", ".//{*}StatusApplicationControl", "End", "2000-01-01"),
        ("ari_avail", ".//{*}RestrictionStatus", "Status", "Maybe"),
        ("ari_inv", ".//{*}InvCount", "CountType", "1"),
        ("ari_inv", ".//{*}InvCount", "Count", "-1"),
    ],
)
def test_structural_checks_detect_corruption(engine, hotel, kind, path, attribute, value):
    feeds = ari.build(engine, StayRequest(hotel_id=hotel.id, checkin=dubai_today()))
    feed = next(f for f in feeds if f.kind == kind)
    root = parse(feed.xml)
    root.find(path).set(attribute, value)
    result = validate(etree.tostring(root), kind)
    assert not result["valid"] and result["check"] == "structural"


def test_recursive_fetch_and_absolute_xml_import_rewrite(tmp_path):
    module = runpy.run_path(str(ROOT / "scripts/fetch_xsd.py"))
    xs = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'
    roots = module["SCHEMAS"]
    base = module["BASE"]
    documents = {url: f"<xs:schema {xs}/>".encode() for url in roots.values()}
    documents[roots["local_feed.xsd"]] = (
        f"<xs:schema {xs}><xs:import "
        'namespace="http://www.w3.org/XML/1998/namespace" '
        'schemaLocation="http://www.w3.org/2001/03/xml.xsd"/></xs:schema>'
    ).encode()
    documents[roots["transaction.xsd"]] = (
        f'<xs:schema {xs}><xs:include schemaLocation="level_one.xsd"/></xs:schema>'
    ).encode()
    documents[base + "level_one.xsd"] = (
        f'<xs:schema {xs}><xs:include schemaLocation="level_two.xsd"/></xs:schema>'
    ).encode()
    documents[base + "level_two.xsd"] = f"<xs:schema {xs}/>".encode()
    documents[module["XML_URL"]] = f"<xs:schema {xs}/>".encode()
    seen = []

    def opener(request, timeout):
        seen.append(request.full_url)
        return io.BytesIO(documents[request.full_url])

    manifest = module["fetch"](tmp_path, opener)
    assert len(seen) == len(set(seen)) == 7
    assert len(manifest["files"]) == 7
    assert b'schemaLocation="xml.xsd"' in (tmp_path / "local_feed.xsd").read_bytes()
    assert b'schemaLocation="level_two.xsd"' in (tmp_path / "level_one.xsd").read_bytes()
    assert json.loads((tmp_path / "manifest.json").read_text())["fetched_at"]
    assert all(f["url"].startswith("https://") and f["source_sha256"] for f in manifest["files"])
    assert Path(XSD_DIR).name == "xsd"

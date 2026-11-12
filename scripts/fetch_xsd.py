"""Cache Google's published schemas and all includes/imports for offline validation.

Run on a machine with network: python scripts/dev.py scripts/fetch_xsd.py
No Google Hotels API endpoint is called. Existing files survive failed fetches.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "rate_truth/feeds/xsd"
BASE = "https://www.gstatic.com/ads-travel/hotels/api/"
SCHEMAS = {
    "local_feed.xsd": "https://www.gstatic.com/localfeed/local_feed.xsd",
    **{n: BASE + n for n in ("transaction.xsd", "transaction_property_data.xsd", "query.xsd")},
}
XML_URL = "https://www.w3.org/2001/03/xml.xsd"
XS = "{http://www.w3.org/2001/XMLSchema}"


def fetch(destination=DEST, opener=urlopen):
    documents, origins = {}, {}

    def visit(url):
        parsed = urlsplit(url)
        if parsed.hostname not in {"www.gstatic.com", "gstatic.com", "www.w3.org"}:
            raise ValueError("Unexpected schema host")
        if parsed.hostname == "www.w3.org" and url != XML_URL:
            raise ValueError("Only W3C xml.xsd is allowed")
        name = Path(parsed.path).name
        if not name.endswith(".xsd"):
            raise ValueError("Expected an XSD")
        if name in origins:
            if origins[name] != url:
                raise ValueError("Schema filename collision")
            return
        origins[name] = url
        req = Request(url, headers={"User-Agent": "rate-truth-research/0.1"})
        with opener(req, timeout=60) as response:
            raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("Schema too large")
        doc = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
        if doc.getroottree().docinfo.doctype or doc.tag != XS + "schema":
            raise ValueError("Expected a schema without a DTD")
        for node in doc.iter():
            if node.tag not in {XS + "include", XS + "import", XS + "redefine"}:
                continue
            location = node.get("schemaLocation")
            if not location:
                continue
            target = urljoin(url, location)
            if Path(urlsplit(target).path).name == "xml.xsd":
                target = XML_URL
            target = target.replace("http://", "https://", 1)
            visit(target)
            node.set("schemaLocation", Path(urlsplit(target).path).name)
        local = etree.tostring(doc, xml_declaration=True, encoding="UTF-8")
        documents[name] = (local, hashlib.sha256(raw).hexdigest())

    for url in SCHEMAS.values():
        visit(url)
    fetched_at = datetime.now(UTC).isoformat()
    destination.mkdir(parents=True, exist_ok=True)
    for name, (local, _) in documents.items():
        temporary = destination / f"{name}.tmp"
        temporary.write_bytes(local)
        temporary.replace(destination / name)
    manifest = {
        "fetched_at": fetched_at,
        "files": [
            {
                "filename": name,
                "url": origins[name],
                "fetched_at": fetched_at,
                "source_sha256": original_hash,
                "local_sha256": hashlib.sha256(local).hexdigest(),
            }
            for name, (local, original_hash) in sorted(documents.items())
        ],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (destination / "FETCHED_AT").write_text(fetched_at + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEST)
    args = parser.parse_args()
    try:
        result = fetch(args.output)
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        parser.exit(1, f"XSD fetch failed: {exc}\n")
    print(f"Fetched {len(result['files'])} schemas at {result['fetched_at']}")


if __name__ == "__main__":
    main()

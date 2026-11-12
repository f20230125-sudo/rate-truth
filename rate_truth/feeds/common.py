"""lxml-only XML creation, with trace records kept alongside published schemas."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from lxml import etree

from rate_truth.contract import DUBAI

OTA = "http://www.opentravel.org/OTA/2003/05"


def element(parent, name, value=None, **attrs):
    child = etree.SubElement(parent, name, **{k: str(v) for k, v in attrs.items()})
    if value is not None:
        child.text = str(value)
    return child


def timestamp():
    return datetime.now(DUBAI).isoformat()


def transaction_root():
    return etree.Element(
        "Transaction", timestamp=timestamp(), id=uuid4().hex, partner="rate-truth-synthetic"
    )


@dataclass
class Feed:
    kind: str
    xml: bytes
    folios: list[dict] = field(default_factory=list)

    @property
    def filename(self):
        return f"{self.kind}.xml"

    @classmethod
    def create(cls, kind, root, folios=None):
        return cls(
            kind,
            etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True),
            folios or [],
        )

    def output(self):
        from rate_truth.feeds.validate import validate

        return {
            "kind": self.kind,
            "filename": self.filename,
            "bytes": len(self.xml),
            "xml": self.xml.decode(),
            "synthetic": True,
            "traces": [
                {"rate_id": f["rate_id"], "computed_at": f["computed_at"]} for f in self.folios
            ],
            **validate(self.xml, self.kind),
        }

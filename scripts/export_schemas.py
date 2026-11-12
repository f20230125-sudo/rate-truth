"""Generate JSON Schema 2020-12 artifacts from the API's Pydantic response models."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.settings import ROOT
from rate_truth.web import models as m

SCHEMAS = {
    "market": m.MarketCheck,
    "market-summary": m.MarketSummary,
    "mcp": m.MCPResponse,
    "mcp-request": m.MCPRequest,
    "meta": m.Meta,
    "hotels": m.Hotels,
    "hotel": m.HotelDetail,
    "quote": m.Folio,
    "ask-request": m.AskRequest,
    "holds": m.Hold,
    "hold-request": m.HoldBody,
    "accuracy": m.Accuracy,
    "accuracy-faults": m.Accuracy,
    "faults": m.Faults,
    "feeds": m.Feeds,
    "taxes": m.Taxes,
    "eval": m.Eval,
    "eval-run": m.Eval,
    "error": m.Error,
    **{k if k != "error" else "stream-error": v for k, v in m.EVENTS.items()},
}


def main():
    directory = ROOT / "docs/schemas"
    directory.mkdir(exist_ok=True)
    for name, model in SCHEMAS.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(mode="serialization"),
        }
        (directory / f"{name}.json").write_text(
            json.dumps(schema, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()

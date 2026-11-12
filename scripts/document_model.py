"""Regenerate the supplier parameter table from the rate engine constants."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.settings import ROOT  # noqa: E402
from rate_truth.supplier import rates as r  # noqa: E402


def parameter_table():
    rows = [
        ("Base by pricing class (AED)", "; ".join(f"{k}: {v}" for k, v in r.BASE_BY_STARS.items())),
        (
            "Area factors (eastern, western, central, northern, other)",
            ", ".join(map(str, r.AREA_FACTORS.values())),
        ),
        (
            "Stable property range",
            f"{r.PROPERTY_MIN / 100:.2f}–{(r.PROPERTY_MIN + r.PROPERTY_STEPS - 1) / 100:.2f}",
        ),
        ("Room factors", "; ".join(f"{k.value}: {v}" for k, v in r.ROOM_FACTOR.items())),
        ("Season (Nov–Mar; Jun–Sep; Apr/May/Oct)", "; ".join(map(str, r.SEASON_FACTORS.values()))),
        ("Friday/Saturday", str(r.WEEKEND_FACTOR)),
        ("Yield", f"{r.YIELD_BASE} + {r.YIELD_SPREAD} × baseline sold / capacity"),
        ("Non-refundable room multiplier", str(r.NONREF_FACTOR)),
        ("LOS discount", "; ".join(f">={k} nights: {v}" for k, v in r.LOS_DISCOUNTS.items())),
        ("Breakfast AED per guest per night", str(r.BREAKFAST_PER_GUEST)),
    ]
    return "| Component | Model |\n| --- | --- |\n" + "\n".join(f"| {a} | {b} |" for a, b in rows)


def main():
    path = ROOT / "docs/supplier-model.md"
    content = path.read_text(encoding="utf-8")
    start = content.index("| Component | Model |")
    end = content.index("\n\nPricing bands", start)
    path.write_text(content[:start] + parameter_table() + content[end:], encoding="utf-8")


if __name__ == "__main__":
    main()

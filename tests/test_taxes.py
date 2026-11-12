from datetime import date
from decimal import Decimal

import pytest

from rate_truth.supplier.models import money
from rate_truth.supplier.taxes import TaxRules


@pytest.mark.parametrize(
    ("base", "stars", "expected", "total"),
    [
        # 1000 * .10 = 100; 1000 * .07 = 70; (1000+100)*.05 = 55; TD=20.
        # 1000 + 100 + 70 + 55 + 20 = 1245.00 AED (five-star, one room-night).
        ("1000.00", 5, ["100.00", "70.00", "55.00", "20.00"], "1245.00"),
        # 200*.10=20; 200*.07=14; (200+20)*.05=11; TD=7.
        # 200 + 20 + 14 + 11 + 7 = 252.00 AED (one-star).
        ("200.00", 1, ["20.00", "14.00", "11.00", "7.00"], "252.00"),
        # 333.33*.10=33.333 ->33.33; *.07=23.3331 ->23.33;
        # (333.33+33.33)*.05=18.333 ->18.33; TD=15.
        # 333.33+33.33+23.33+18.33+15=423.32 AED (four-star).
        ("333.33", 4, ["33.33", "23.33", "18.33", "15.00"], "423.32"),
        # 0.50*.10=.05; .50*.07=.035 ->.04 (HALF_UP, not bankers' rounding);
        # (.50+.05)*.05=.0275 ->.03; TD=10 even with a very cheap room.
        # .50+.05+.04+.03+10=10.62 AED (two-star).
        ("0.50", 2, ["0.05", "0.04", "0.03", "10.00"], "10.62"),
        # Complimentary room: 0+0+0+0+10=10; Tourism Dirham still applies.
        ("0.00", 3, ["0.00", "0.00", "0.00", "10.00"], "10.00"),
    ],
)
def test_hand_worked_examples(base, stars, expected, total):
    items = TaxRules().for_night(Decimal(base), date(2026, 11, 11), stars)
    assert [str(item.amount) for item in items] == expected
    assert money(Decimal(base) + sum(item.amount for item in items)) == Decimal(total)
    assert all(item.rule_id and item.source.startswith("https://") for item in items)
    assert items[2].taxable_base == Decimal(base) + items[0].amount


@pytest.mark.parametrize("stars,fee", [(1, "7"), (2, "10"), (3, "10"), (4, "15"), (5, "20")])
def test_all_hotel_categories(stars, fee):
    assert TaxRules().for_night(Decimal(100), date(2026, 11, 11), stars)[3].amount == Decimal(fee)


@pytest.mark.parametrize(
    "night,coastal,expected_rule,status",
    [
        ("2026-03-31", False, None, "normal"),
        (
            "2026-04-01",
            True,
            "resolution_40_2026_initial_remittance_exemption",
            "remittance_exempt",
        ),
        (
            "2026-06-30",
            False,
            "resolution_40_2026_initial_remittance_exemption",
            "remittance_exempt",
        ),
        (
            "2026-07-01",
            False,
            "resolution_40_2026_extended_remittance_exemption",
            "remittance_exempt",
        ),
        ("2026-07-01", True, None, "normal"),
        (
            "2026-07-01",
            None,
            "resolution_40_2026_extended_remittance_exemption",
            "eligibility_unknown",
        ),
        (
            "2026-09-30",
            False,
            "resolution_40_2026_extended_remittance_exemption",
            "remittance_exempt",
        ),
        ("2026-10-01", False, None, "normal"),
        ("2026-11-11", False, None, "normal"),
    ],
)
def test_effective_date_switching_without_inventing_guest_waiver(
    night, coastal, expected_rule, status
):
    items = TaxRules().for_night(Decimal(1000), date.fromisoformat(night), 5, coastal=coastal)
    assert items[1].remittance_rule_id == items[3].remittance_rule_id == expected_rule
    assert items[1].remittance_status == items[3].remittance_status == status
    # Resolution exempts remitting collected proceeds, not collecting guest charges:
    # 1000 +100 +70 +55 +20 =1245 in all phases; service and VAT stay in force.
    assert sum(item.amount for item in items) == Decimal("245.00")
    assert items[0].remittance_rule_id is None and items[2].remittance_rule_id is None


def test_unsupported_dates_and_invalid_inputs():
    taxes = TaxRules()
    for day in (date(2024, 12, 31), date(2029, 1, 1)):
        with pytest.raises(ValueError):
            taxes.at(day)
    for base in (Decimal(-1), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError):
            taxes.for_night(base, date(2026, 11, 11), 5)


def test_all_values_have_provenance_and_uncertainty():
    data = TaxRules().data
    for rule in data["rules"] + data["relief"]:
        assert rule["source"].startswith("https://")
        assert rule["accessed"] == "2026-11-11"
        assert rule["confidence"] in {"official", "secondary"}
    td = next(r for r in data["rules"] if r["kind"] == "tourism_dirham")
    for value in list(td["hotel_categories"].values()) + list(td["other_categories"].values()):
        assert value["source"] and value["accessed"] and value["confidence"]
    assert data["rules"][0]["confidence"] == "secondary"
    assert data["rules"][2]["base_confidence"] == "secondary"


def test_effective_dated_rate_stack_is_selected_from_data(tmp_path):
    import yaml

    data = TaxRules().data
    service = data["rules"][0]
    service["effective_to"] = "2026-12-31"
    # Explicit test-only future change verifies selection, not a claimed real law.
    data["rules"].append(
        {
            **service,
            "id": "TEST_ONLY_new_rate",
            "rate": "0.12",
            "effective_from": "2027-01-01",
            "effective_to": None,
        }
    )
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    taxes = TaxRules(path)
    before = taxes.for_night(Decimal(100), date(2026, 12, 31), 5)
    after = taxes.for_night(Decimal(100), date(2027, 1, 1), 5)
    assert before[0].amount == Decimal(10)
    assert after[0].amount == Decimal(12)
    assert after[0].rule_id == "TEST_ONLY_new_rate"

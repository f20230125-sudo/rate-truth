"""Regression: amounts at the end of a sentence must still be found and checked.

Found on the live site on 12 Nov 2026: "...with a total price of AED 1686.44." produced
zero detected prices, so an invented amount written the same way would have passed.
"""

import pytest

from rate_truth.rag.cite import amounts, ground


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Total price of AED 1686.44.", ["1686.44"]),
        ("It costs AED 1,686.44, all-in.", ["1686.44"]),
        ("Pay AED 1686.44; taxes included.", ["1686.44"]),
        ("(AED 1686.44)", ["1686.44"]),
        ("1686.44 AED.", ["1686.44"]),
        ("From AED 900 to AED 1,200.", ["900.00", "1200.00"]),
    ],
)
def test_amounts_survive_sentence_punctuation(text, expected):
    assert amounts(text) == expected


def test_sub_fils_amount_is_caught_and_never_traced():
    # "AED 1686.444" is still a price mention; it must not match the 1686.44 folio.
    prices, _, grounding = ground("Pay AED 1686.444 today.", [{"folio": folio("1686.44")}])
    assert len(prices) == 1 and prices[0]["traced"] is False
    assert grounding["ok"] is False


def folio(total):
    return {
        "rate_id": "rt_test",
        "total": total,
        "lines": [{"amount": total}],
        "synthetic": True,
        "hotel_id": "node/1",
    }


def test_untraced_amount_at_sentence_end_is_flagged():
    prices, _, grounding = ground("A fair price is AED 999.00.", [{"folio": folio("1686.44")}])
    assert [p["amount"] for p in prices] == ["999.00"]
    assert grounding["ok"] is False
    assert grounding["untraced"] == ["999.00"]


def test_traced_amount_at_sentence_end_is_grounded():
    prices, _, grounding = ground("Total price of AED 1686.44.", [{"folio": folio("1686.44")}])
    assert prices[0]["traced"] and prices[0]["rate_id"] == "rt_test"
    assert grounding["ok"] is True and grounding["traced"] == 1

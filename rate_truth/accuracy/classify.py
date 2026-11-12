"""Evidence-based classification independent of the injected fault label."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from rate_truth.accuracy.reasons import GOOGLE_REASONS
from rate_truth.feeds.validate import parse


def is_listed(feed, hotel_list_xml):
    return hotel_list_xml is None or feed["hotel_id"] in {
        node.text for node in parse(hotel_list_xml).findall("listing/id")
    }


def classify(feed, landing, *, hotel_list_xml=None, tax_rules=None):
    reason, diagnosis, evidence = None, None, []
    feed_rules = {i["rule_id"] for i in feed["lines"]}
    missing = [i for i in landing["lines"] if i["rule_id"] not in feed_rules]
    delta = abs(Decimal(feed["total"]) - Decimal(landing["total"]))
    if not is_listed(feed, hotel_list_xml):
        reason, diagnosis = "SITE_ERROR", "hotel_not_listed"
        evidence = ["Hotel absent from hotel-list membership set"]
    elif any(feed[k] != landing[k] for k in ("hotel_id", "checkin", "nights", "guests")):
        reason, diagnosis = "WRONG_ITINERARY", "los_mismatch"
        evidence = ["Feed and landing itinerary fields differ"]
    elif missing:
        reason, diagnosis = "TAX_MISMATCH", "taxes_fees_omitted"
        evidence = [f"Missing rule {i['rule_id']} ({i['label']})" for i in missing]
        if {i["label"] for i in missing} == {"Municipality fee", "Tourism Dirham"} and tax_rules:
            day = date.fromisoformat(landing["checkin"])
            for window in tax_rules.get("relief", []):
                if (
                    window["id"].startswith("resolution_40_2026_")
                    and set(window.get("affects", [])) == {"municipality", "tourism_dirham"}
                    and date.fromisoformat(window["effective_from"])
                    <= day
                    <= date.fromisoformat(window["effective_to"])
                ):
                    diagnosis = "tax_rule_change_missed"
                    evidence.extend([window["source"], window["traveller_charge_effect"]])
                    break
    elif delta:
        age = datetime.fromisoformat(landing["computed_at"]) - datetime.fromisoformat(
            feed["computed_at"]
        )
        if age > timedelta(hours=24):
            reason, diagnosis = "PRICE_FEED_DELAYED", "stale_cache"
            evidence = ["Feed computed_at precedes landing by more than 24h"]
        elif delta <= Decimal("0.05"):
            reason, diagnosis = "MISMATCH_REASON_UNSPECIFIED", "currency_rounding"
            evidence = ["Difference <= AED 0.05; consistent with rounding, not proof of conversion"]
        else:
            fb = sum(Decimal(i["amount"]) for i in feed["lines"] if i["kind"] == "base")
            lb = sum(Decimal(i["amount"]) for i in landing["lines"] if i["kind"] == "base")
            discount = Decimal("0.10") if landing["nights"] >= 7 else Decimal("0.05")
            if landing["nights"] >= 3 and abs(fb * (1 - discount) - lb) <= Decimal("0.30"):
                reason, diagnosis = "DISCOUNT_MISSING", "missing_discount"
                evidence = ["Base difference agrees with documented supplier LOS discount"]
            else:
                reason = "MISMATCH_REASON_UNSPECIFIED"
                evidence = ["Price differs; insufficient evidence for a more specific reason"]
    return {
        "reason": reason,
        "diagnosis": diagnosis,
        "evidence": evidence,
        "source_url": GOOGLE_REASONS,
    }


def matches(feed, landing, *, hotel_list_xml=None):
    if not is_listed(feed, hotel_list_xml) or any(
        feed[k] != landing[k] for k in ("hotel_id", "checkin", "nights", "guests")
    ):
        return False
    delta = abs(Decimal(feed["total"]) - Decimal(landing["total"]))
    return delta <= max(Decimal("1.00"), Decimal(landing["total"]) * Decimal("0.01"))

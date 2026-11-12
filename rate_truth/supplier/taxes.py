"""Effective-dated charges. Remittance relief never silently reduces guest charges."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from rate_truth.settings import DATA
from rate_truth.supplier.models import LineItem, money


class OutOfModelPeriod(ValueError):
    code = "out_of_model_period"


class TaxRules:
    def __init__(self, path: Path | None = None):
        raw = (path or DATA / "tax_rules.yaml").read_bytes()
        self.fingerprint = hashlib.sha256(raw).hexdigest()
        self.data = yaml.safe_load(raw)

    @staticmethod
    def active(rule: dict, night: date) -> bool:
        return date.fromisoformat(rule["effective_from"]) <= night and (
            rule.get("effective_to") is None or night <= date.fromisoformat(rule["effective_to"])
        )

    def at(self, night: date, coastal: bool | None = None) -> dict:
        if not self.active(self.data["model_period"], night):
            raise OutOfModelPeriod("stay is outside the documented tax model period")
        rules = {}
        for kind in ("service_charge", "municipality", "vat", "tourism_dirham"):
            matches = [r for r in self.data["rules"] if r["kind"] == kind and self.active(r, night)]
            if len(matches) != 1:
                raise ValueError(f"ambiguous or missing tax rule: {kind}")
            rules[kind] = matches[0]
        relief = []
        for r in self.data["relief"]:
            if not r.get("engine_active", False) or not self.active(r, night):
                continue
            status = "remittance_exempt"
            if r.get("excludes_coastal"):
                if coastal is True:
                    continue
                if coastal is None:
                    status = "eligibility_unknown"
            relief.append({**r, "status": status})
        return {"rules": rules, "relief": relief}

    def for_night(
        self,
        base: Decimal,
        night: date,
        stars: int,
        rooms: int = 1,
        coastal: bool | None = None,
        consecutive_night: int = 1,
    ) -> list[LineItem]:
        if (
            not base.is_finite()
            or base < 0
            or stars not in range(1, 6)
            or type(rooms) is not int
            or rooms < 1
            or type(consecutive_night) is not int
            or consecutive_night < 1
        ):
            raise ValueError("invalid tax inputs")
        base = money(base)
        selection = self.at(night, coastal)
        amounts = {"base": base}
        result = []
        for kind in ("service_charge", "municipality", "vat", "tourism_dirham"):
            rule = selection["rules"][kind]
            tax_base = sum((amounts[k] for k in rule["base_components"]), Decimal(0))
            if kind == "tourism_dirham":
                category = rule["hotel_categories"][str(stars)]
                amount = money(Decimal(category["amount"]) * rooms)
                if consecutive_night > rule["max_consecutive_nights"]:
                    amount = money(0)
                evidence = category
            else:
                amount = money(tax_base * Decimal(rule["rate"]))
                evidence = rule
            amounts[kind] = amount
            relief = next((r for r in selection["relief"] if kind in r["affects"]), None)
            result.append(
                LineItem(
                    rule_id=rule["id"],
                    name=kind,
                    date=night,
                    amount=amount,
                    taxable_base=money(tax_base),
                    source=evidence["source"],
                    accessed=evidence["accessed"],
                    confidence=evidence["confidence"],
                    base_confidence=rule["base_confidence"],
                    remittance_rule_id=relief["id"] if relief else None,
                    remittance_status=relief["status"] if relief else "normal",
                )
            )
        return result

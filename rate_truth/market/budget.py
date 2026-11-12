"""Reserve every SerpApi request before network I/O, never beyond 220 UTC-month calls."""

import os

from rate_truth.market.base import MarketError
from rate_truth.market.storage import file_lock, market_dir, read_json, utcnow, write_json

CAP = 220


class Budget:
    def __init__(self, path=None, clock=utcnow):
        self.path = path or market_dir() / "budget.json"
        self.clock = clock

    def _state(self):
        month = self.clock().strftime("%Y-%m")
        try:
            state = read_json(self.path, {"month": month, "used": 0})
        except (ValueError, OSError):
            raise MarketError(
                "market_budget_unavailable", "market budget state is unreadable"
            ) from None
        if (
            not isinstance(state, dict)
            or not isinstance(state.get("month"), str)
            or type(state.get("used")) is not int
            or state["used"] < 0
        ):
            raise MarketError("market_budget_unavailable", "market budget state is invalid")
        return state if state["month"] == month else {"month": month, "used": 0}

    def status(self):
        state = self._state()
        return {**state, "cap": CAP, "remaining": max(0, CAP - state["used"])}

    def reserve(self):
        # Vercel's /tmp cannot enforce a persistent deployment-wide monthly allowance.
        # Fail closed for B unless the operator configures a genuinely shared durable volume.
        if os.getenv("VERCEL") and os.getenv("RATE_TRUTH_MARKET_PERSISTENT") != "true":
            raise MarketError(
                "market_budget_unavailable", "SerpApi needs shared persistent storage"
            )
        with file_lock(str(self.path) + ".lock", timeout=2):
            state = self._state()
            if state["used"] >= CAP:
                raise MarketError(
                    "market_budget_exhausted", "monthly market search budget exhausted"
                )
            state["used"] += 1
            write_json(self.path, state)
            return state

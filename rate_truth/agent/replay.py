"""Exact live response replay when recorded; explicitly labelled scripted demos otherwise."""

import html
import json
from pathlib import Path

from rate_truth.agent.llm.store import Completion
from rate_truth.rag.cite import folios_in

DIRECTORY = Path(__file__).with_suffix("")
SUGGESTIONS = [
    "Find a refundable stay near a metro for two nights.",
    "Compare two hotels and explain every fee.",
    "Find a stay and prepare a mock hold.",
]


class ReplayLLM:
    def __init__(self, message, today, gateway, *, retry_after_s=None):
        self.message, self.today, self.gateway = message, today, gateway
        self.retry_after_s = retry_after_s
        self.position = 0
        self.record = next(
            (
                json.loads(p.read_text(encoding="utf-8"))
                for p in DIRECTORY.glob("*.json")
                if json.loads(p.read_text(encoding="utf-8")).get("message") == message
            ),
            None,
        )
        self.responses = self.record.get("responses") if self.record else None

    def complete(self, messages, **kwargs):
        if self.responses:
            response = self.responses[self.position]
            self.position += 1
            return Completion(response, 0, 0, "recorded-live-replay")
        outputs = []
        for message in messages:
            if message["content"].startswith("<tool_outputs>"):
                outputs.append(
                    json.loads(
                        html.unescape(message["content"].split("\n", 1)[1].rsplit("\n", 1)[0])
                    )
                )
        plan = self.record.get("plan", []) if self.record else []
        if self.position < len(plan):
            action = plan[self.position]
            self.position += 1
            args = dict(action.get("args", {}))
            folios = folios_in(outputs)
            identifiers = list(dict.fromkeys(f["hotel_id"] for f in folios))
            first = (
                identifiers[0] if identifiers else next(iter(self.gateway.engine.catalog.hotels))
            )
            for key, value in list(args.items()):
                if value == "$today":
                    args[key] = self.today.isoformat()
                elif value == "$first":
                    args[key] = first
                elif value == "$two":
                    args[key] = identifiers[:2] or [first]
            result = {"action": "call", "tool": action["tool"], "args": args}
        else:
            folios = folios_in(outputs)
            # Avoid repeating any untrusted OSM name in scripted prose.
            if folios:
                shown = folios[-2:]
                text = "Offline scripted MCP demonstration; synthetic supplier prices. " + " ".join(
                    f"Option {i}: AED {f['total']} all-in ({f['rate_id']})."
                    for i, f in enumerate(shown, 1)
                )
                text += " Rates include the fee lines shown in the folios."
            else:
                text = "The live model is busy (free-tier limit). "
                text += "Try one of the three recorded demos, or ask again in a minute."
            result = {
                "action": "answer",
                "text": text,
                "cited_cards": [],
                "hold_rate_id": folios[-1]["rate_id"]
                if folios and any(w in self.message.casefold() for w in ("hold", "reserve", "book"))
                else None,
            }
            if not folios and self.retry_after_s is not None:
                result["retry_after_s"] = self.retry_after_s
        return Completion(json.dumps(result), 0, 0, "scripted-offline-demo")

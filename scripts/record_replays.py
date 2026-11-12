"""Network-enabled reviewer command: record 3 suggested asks + 10 independent eval tasks."""

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.common import atomic_json, fixed_today
from eval.run_eval import QUOTA_ERRORS, LiveLLM, gemini_limits
from rate_truth.agent.config import load_env
from rate_truth.agent.loop import Agent
from rate_truth.agent.replay import DIRECTORY, SUGGESTIONS
from rate_truth.mcp_server.server import create_server
from rate_truth.mcp_server.service import Gateway
from rate_truth.settings import ROOT


class RecordingLLM:
    def __init__(self, llm):
        self.llm, self.responses = llm, []

    def complete(self, *args, **kwargs):
        response = self.llm.complete(*args, **kwargs)
        self.responses.append(response.text)
        return response


async def main():
    load_env()
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Set GEMINI_API_KEY in .env; no key values are printed.")
    tasks = [
        json.loads(line) for line in (ROOT / "eval/tasks_shopper.jsonl").read_text().splitlines()
    ][:10]
    gateway = Gateway()
    agent = Agent(create_server(gateway), gateway)
    cases = [(f"demo-{i + 1}", ask) for i, ask in enumerate(SUGGESTIONS)]
    cases += [(t["id"], t["ask"]) for t in tasks]
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    llm = LiveLLM(model, gemini_limits(model))
    outcomes = []
    try:
        # A single client/budget spans all tasks; no cache or provider fallback.
        with fixed_today(), patch("rate_truth.agent.loop.TURN_BUDGET_S", float("inf")):
            for identifier, message in cases:
                llm.responses, llm.error = [], None
                recorder = RecordingLLM(llm)
                events = [
                    {"event": event, "data": data}
                    async for event, data in agent.stream(
                        message, today=date(2026, 11, 12), llm=recorder
                    )
                ]
                if llm.error in QUOTA_ERRORS:
                    outcomes.append({"id": identifier, "status": "quota_error"})
                    print(f"{identifier}: quota_error (recording not saved)")
                    continue
                if llm.error or not save_recording(identifier, message, recorder.responses, events):
                    outcomes.append({"id": identifier, "status": "recording_error"})
                    print(f"{identifier}: no successful tool run; recording not saved")
                    continue
                outcomes.append({"id": identifier, "status": "saved"})
                print(f"{identifier}: saved sanitised live run")
    finally:
        llm.close()
        summary = {
            "n": len(outcomes), "expected_n": len(cases), "tasks": outcomes,
            "saved_count": sum(t["status"] == "saved" for t in outcomes),
            "quota_error_count": sum(t["status"] == "quota_error" for t in outcomes),
            "quota_error_ids": [t["id"] for t in outcomes if t["status"] == "quota_error"],
        }
        atomic_json(ROOT / ".local/record-replays-summary.json", summary)
        print(json.dumps(summary))
    return summary


def save_recording(identifier, message, responses, events):
    # No keys, HTTP headers, tokens or provider error bodies enter this artifact.
    if not responses or not any(e["event"] == "trace" and e["data"].get("ok") for e in events):
        return False
    record = {
        "provenance": "live_llm_recording",
        "today": "2026-11-12",
        "message": message,
        "responses": responses,
        "events": events,
    }
    serialized = json.dumps(record, ensure_ascii=False, indent=2)
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        secret = os.environ.get(key)
        if secret and secret in serialized:
            raise RuntimeError("recording rejected by secret scrubber")
    (DIRECTORY / f"{identifier}.json").write_text(serialized, encoding="utf-8")
    return True


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(main())

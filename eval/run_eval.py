"""Evaluate every reviewer task through the production Agent and its real MCP server."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.common import ROOT, TODAY, atomic_json, fixed_today, now, update_results
from eval.scoring import aggregate, score_task
from rate_truth.agent.config import load_env
from rate_truth.agent.llm.budget import Budget, CallTooLarge, DailyLimitReached, Limits
from rate_truth.agent.llm.providers import Gemini, RateLimited
from rate_truth.agent.llm.router import estimate_tokens
from rate_truth.agent.llm.store import Store
from rate_truth.agent.loop import TURN_BUDGET_S, Agent
from rate_truth.agent.replay import ReplayLLM
from rate_truth.mcp_server.server import create_server, failure
from rate_truth.mcp_server.service import Gateway

SHOPPER = {
    "search_hotels", "get_rates", "check_availability", "recommend_hotels", "compare_hotels",
    "hold_offer", "market_check",
}
OPS = {
    "build_hotel_list_feed", "build_ari_messages", "validate_feed", "run_price_accuracy_audit",
    "explain_mismatch", "tax_rules_at",
}


def tasks():
    return [
        {**json.loads(line), "role": role}
        for role in ("shopper", "ops")
        for line in (ROOT / f"eval/tasks_{role}.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sanitise(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if "token" in k.lower() or "api_key" in k.lower()
                else sanitise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitise(v) for v in value]
    if isinstance(value, str):
        # Model protocol responses are JSON strings; redact capabilities inside them too.
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            value = json.dumps(sanitise(parsed), ensure_ascii=False)
        for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "SERPAPI_API_KEY", "RATE_TRUTH_SECRET"):
            secret = os.environ.get(key)
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


def gemini_limits(model):
    load_env()
    raw = os.environ.get("GEMINI_LIMITS")
    if raw is None:
        for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines() \
                if (ROOT / ".env").exists() else []:
            key, sep, value = line.strip().partition("=")
            if sep and key == "GEMINI_LIMITS":
                raw = value.strip().strip("'")
    values = json.loads(raw) if raw else {}
    values = values.get(model, values)
    defaults = {"rpm": 6, "tpm": 60000, "rpd": 200, "tpd": 1000000}
    limits = Limits(**{k: int(values.get(k, v)) for k, v in defaults.items()})
    if min(limits.rpm, limits.tpm, limits.rpd, limits.tpd) <= 0:
        raise ValueError("GEMINI_LIMITS values must be positive")
    return limits


QUOTA_ERRORS = {RateLimited.__name__, DailyLimitReached.__name__, CallTooLarge.__name__}


class LiveLLM:
    """The existing Gemini REST provider, with per-call pacing and durable quota counters.

    No fallback or cache can silently turn a live evaluation into replay.
    """

    def __init__(self, model, limits):
        self.model, self.limits = model, limits
        self.provider = Gemini(os.environ["GEMINI_API_KEY"], default_timeout_s=15.0)
        self.store = Store(ROOT / ".local/m5-gemini.sqlite")
        self.budget = Budget(
            "m5-gemini:" + model, limits, self.store, wait_for_minute=True,
            clock=time.time, sleep=time.sleep,
        )
        self.last_call = 0.0
        self.responses = []
        self.error = None

    @property
    def interval(self):
        return 60 / self.limits.rpm + 0.1

    def complete(self, messages, **kwargs):
        for retry in range(2):
            attempt = {"messages": list(messages), "model": self.model}
            self.responses.append(attempt)
            time.sleep(max(0, self.last_call + self.interval - time.monotonic()))
            booking = None
            try:
                booking = self.budget.reserve(
                    estimate_tokens(messages, kwargs.get("max_tokens", 1800))
                )
                self.last_call = time.monotonic()
                response = self.provider.chat(self.model, messages, temperature=0.0, **kwargs)
                self.budget.settle(booking, response.prompt_tokens + response.completion_tokens)
                attempt.update(
                    response=response.text, model=response.model, latency_ms=response.latency_ms
                )
                self.error = None
                return response
            except Exception as exc:
                if booking:
                    self.budget.release(booking)
                # Retain only a type, never a provider body, URL, header, or credential.
                attempt["error"] = type(exc).__name__
                if isinstance(exc, RateLimited) and retry == 0:
                    time.sleep(max(0, exc.retry_after if exc.retry_after is not None else 60))
                    continue
                self.error = type(exc).__name__
                raise

    def close(self):
        self.provider.client.close()
        self.store.close()


def instrument(server, allowed, calls):
    original_list, original_call = server.list_tools, server.call_tool

    async def list_tools(*args, **kwargs):
        return [t for t in await original_list(*args, **kwargs) if t.name in allowed]

    async def call_tool(name, arguments, context=None):
        entry = {"tool": name, "args": dict(arguments), "ok": False}
        calls.append(entry)
        # Evaluation must never interfere with an in-progress market snapshot.
        if name == "market_check" and arguments.get("live"):
            result = failure("eval_offline_market", "evaluation uses recorded market data only")
        else:
            result = await original_call(name, arguments, context)
        entry.update(ok=not result.is_error, output=result.structured_content)
        return result

    server.list_tools, server.call_tool = list_tools, call_tool


async def execute(task, mode, live=None):
    gateway, calls = Gateway(), []
    server = create_server(gateway)
    instrument(server, SHOPPER if task["role"] == "shopper" else OPS, calls)
    llm = live or ReplayLLM(task["ask"], TODAY, gateway)
    if live:
        live.responses, live.error = [], None
    record = {"task_id": task["id"], "task_hash": digest(task), "mode": mode,
              "today": TODAY.isoformat(), "run_at": now(), "calls": calls, "events": []}
    try:
        agent = Agent(server, gateway, force_replay=mode == "replay")
        record["events"] = [
            {"event": event, "data": data}
            async for event, data in agent.stream(task["ask"], today=TODAY, llm=llm)
        ]
        record["status"] = "interrupted" if live and live.error else "complete"
    except Exception as exc:
        record.update(status="interrupted", error=type(exc).__name__)
    if live:
        record["responses"] = live.responses
        record["error"] = live.error or record.get("error")
        if record["error"] in QUOTA_ERRORS:
            record["status"] = "quota_error"
    record["score"] = score_task(task, record)
    return record


async def run(args):
    cases = tasks()
    if getattr(args, "rescore", None):
        return rescore(args, cases)
    load_env()
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite") if args.mode == "live" \
        else "recorded-or-scripted-replay"
    if args.mode == "live" and not os.environ.get("GEMINI_API_KEY"):
        raise ValueError("Set GEMINI_API_KEY in .env for --mode live")
    run_id = args.resume or args.run_id or (
        args.mode + "-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    )
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("run ID must contain only letters, numbers, underscore or hyphen")
    directory = ROOT / "eval/raw" / run_id
    manifest_path = directory / "manifest.json"
    limits = gemini_limits(model) if args.mode == "live" else None
    # Provider-directed delays can exceed any fixed turn allowance. Batch runs retain
    # the six-response cap and provider HTTP timeout, while permitting quota waits.
    budget = None if limits else TURN_BUDGET_S
    identity = {"mode": args.mode, "model": model, "today": TODAY.isoformat(),
                "tasks_hash": digest(cases), "turn_budget_s": budget,
                "limits": vars(limits) if limits else None}
    if args.resume:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["identity"] != identity:
            raise ValueError("resume configuration differs from original run")
    else:
        if directory.exists():
            raise ValueError("run directory exists; use --resume RUN_ID")
        manifest = {"run_id": run_id, "run_at": now(), "identity": identity}
        atomic_json(manifest_path, manifest)
    live = LiveLLM(model, limits) if limits else None
    scored, records = [], []
    try:
        # Allow quota sleeps during eval only; retain the production six-response cap.
        with fixed_today(), patch("rate_truth.agent.loop.TURN_BUDGET_S", budget or float("inf")):
            for task in cases:
                path = directory / f"{task['id']}.json"
                previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
                if previous and previous.get("status") == "complete":
                    if previous["task_hash"] != digest(task) or previous["mode"] != args.mode:
                        raise ValueError("saved task does not match this evaluation")
                    record = previous
                else:
                    record = await execute(task, args.mode, live)
                    atomic_json(path, sanitise(record))
                records.append(record)
                if record["status"] == "quota_error":
                    print(f"{task['id']}: quota_error (excluded from accuracy)", flush=True)
                    continue
                scored.append(score_task(task, record))
                print(f"{task['id']}: {'PASS' if scored[-1]['passed'] else 'FAIL'}", flush=True)
                if record["status"] != "complete":
                    print(f"Stopped safely. Resume: --mode {args.mode} --resume {run_id}")
                    break
    finally:
        if live:
            live.close()
    return publish(args, records, scored, identity, run_id, manifest, len(cases))


def rescore(args, cases):
    """Read existing transcripts only; no environment, providers, tools or missing tasks run."""
    run_id = args.rescore
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("invalid run ID")
    directory = ROOT / "eval/raw" / run_id
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    identity = manifest["identity"]
    if identity["tasks_hash"] != digest(cases) or identity["mode"] != args.mode:
        raise ValueError("saved tasks or mode differ")
    records, scored = [], []
    for task in cases:
        path = directory / f"{task['id']}.json"
        if not path.exists():
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["task_hash"] != digest(task) or record["mode"] != args.mode:
            raise ValueError("saved task differs")
        records.append(record)
        score = score_task(task, record)
        if record["status"] != "quota_error":
            scored.append(score)
        print(f"{task['id']}: rescored ({record['status']})", flush=True)
    return publish(args, records, scored, identity, run_id, manifest, len(cases), rescored=True)


def publish(args, records, scored, identity, run_id, manifest, expected_n, *, rescored=False):
    metrics = aggregate(scored)
    result = {
        **identity, "run_id": run_id, "run_at": manifest["run_at"], "finished_at": now(),
        "n": len(records), "expected_n": expected_n, "scored_n": len(scored),
        "quota_error_count": sum(r["status"] == "quota_error" for r in records),
        "quota_error_ids": [r["task_id"] for r in records if r["status"] == "quota_error"],
        "complete": len(records) == expected_n and all(
            r["status"] in {"complete", "quota_error"} for r in records
        ),
        "metrics": metrics, "failing_ids": [s["id"] for s in scored if not s["passed"]],
        "tasks": scored,
        "note": "Replay is an infrastructure smoke, not model quality. Live uses Gemini only; "
                "batch quota waits have no turn deadline; the six-response cap remains. "
                "Quota errors are listed separately and excluded from all accuracy metrics. "
                "Argument accuracy counts exact expected fields; zero denominators are null.",
    }
    if rescored:
        result["rescored_at"] = now()
        result["note"] += " Rescored from recorded outputs and answer text; no model calls."
    update_results("agent" if args.mode == "live" else "agent_replay_smoke", result)
    print(json.dumps({"run_id": run_id, "n": result["n"],
                      "quota_error_count": result["quota_error_count"],
                      "quota_error_ids": result["quota_error_ids"], "metrics": metrics}))
    if not result["complete"] or not any(r["calls"] for r in records):
        return 2
    return int(bool(result["failing_ids"]) and (args.mode == "live" or args.strict))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--rescore", metavar="RUN_ID", help="score existing raw records offline")
    parser.add_argument("--strict", action="store_true", help="fail replay on task failures")
    args = parser.parse_args()
    if sum(bool(v) for v in (args.resume, args.run_id, args.rescore)) > 1:
        parser.error("use only one of --resume, --run-id or --rescore")
    logging.basicConfig(level=logging.ERROR)
    try:
        return asyncio.run(run(args))
    except (ValueError, FileNotFoundError):
        # Configuration values can contain secrets, so do not echo exception text.
        print("Invalid eval configuration or resume; see docs/evaluation.md.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

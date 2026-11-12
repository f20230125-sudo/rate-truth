"""Measure MCP tool round trips over local stateless HTTP (200/tool, concurrency 8)."""

import argparse
import asyncio
import json
import logging
import math
import platform
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import Client

from eval.common import TODAY, bounded_map, fixed_today, local_server, now, update_results
from rate_truth.feeds.hotel_list import build
from rate_truth.mcp_server.server import create_server
from rate_truth.mcp_server.service import Gateway
from rate_truth.supplier.rates import RateEngine


def percentile(values, quantile):
    """Nearest-rank percentile, in milliseconds; no interpolation ambiguity."""
    return sorted(values)[max(0, math.ceil(quantile * len(values)) - 1)]


def workloads(gateway):
    hotel = next(iter(gateway.engine.catalog.hotels.values()))
    stay = {"hotel_id": hotel.id, "checkin": TODAY.isoformat(), "nights": 1}
    return {
        "search_hotels": {"checkin": TODAY.isoformat(), "limit": 5},
        "get_rates": stay,
        "check_availability": stay,
        "recommend_hotels": {"query": "near metro", "checkin": TODAY.isoformat(), "limit": 5},
        "compare_hotels": {"hotel_ids": list(gateway.engine.catalog.hotels)[:2],
                           "checkin": TODAY.isoformat()},
        "market_check": {**stay, "live": False},
        # Exercise the confirmation boundary without creating holds or bypassing throttles.
        "hold_offer": {"rate_id": "rt_" + "0" * 64, "hold_token": "x" * 32, "confirm": False},
        "build_hotel_list_feed": {"hotel_ids": [hotel.id]},
        "build_ari_messages": stay,
        "validate_feed": {"xml": build([hotel]).xml.decode(), "kind": "hotel_list"},
        "run_price_accuracy_audit": {"n": 10, "faults": ["stale_cache"]},
        "explain_mismatch": {"sample_id": "sample-2026-0", "n": 10, "faults": ["stale_cache"]},
        "tax_rules_at": {"day": TODAY.isoformat()},
    }


async def measure(url, tool, arguments, n, concurrency):
    # A bounded pool of SDK clients keeps HTTP connections warm. The server is stateless;
    # no MCP session is created. Handshake/list_tools and semaphore waiting are not timed.
    queue = asyncio.Queue()
    clients = []
    try:
        for _ in range(concurrency):
            client = Client(url, mode="2026-07-28")
            await client.__aenter__()
            clients.append(client)
            queue.put_nowait(client)

        async def call(_):
            client = await queue.get()
            started = time.perf_counter()
            try:
                result = await client.call_tool(tool, arguments)
                code = (result.structured_content or {}).get("error", {}).get("code")
                return (time.perf_counter() - started) * 1000, not result.is_error, code
            except Exception as exc:
                return (time.perf_counter() - started) * 1000, False, type(exc).__name__
            finally:
                queue.put_nowait(client)

        samples = await bounded_map(call, n, concurrency)
    finally:
        for client in reversed(clients):
            await client.__aexit__(None, None, None)
    times = [s[0] for s in samples]
    return {"n": n, "p50_ms": round(percentile(times, 0.50), 3),
            "p95_ms": round(percentile(times, 0.95), 3),
            "successes": sum(s[1] for s in samples), "errors": sum(not s[1] for s in samples),
            "error_codes": dict(Counter(s[2] for s in samples if not s[1])),
            "scenario": "confirmation refusal / throttle" if tool == "hold_offer"
                        else "bounded valid request"}


async def run(args):
    # Stable ADR baseline, no market recalibration while reviewer network jobs are writing.
    gateway = Gateway(RateEngine(market_calibration={}))
    results = {}
    with fixed_today(), local_server(create_server(gateway)) as url:
        async with Client(url, mode="2026-07-28") as client:
            names = {t.name for t in (await client.list_tools()).tools}
        cases = workloads(gateway)
        if names != cases.keys():
            raise RuntimeError("load workloads do not cover every advertised tool")
        for tool, arguments in cases.items():
            results[tool] = await measure(url, tool, arguments, args.calls, args.concurrency)
            print(f"{tool}: {json.dumps(results[tool])}", flush=True)
    update_results("load", {
        "run_at": now(), "transport": "stateless streamable HTTP / MCP 2026-07-28",
        "calls_per_tool": args.calls, "concurrency": args.concurrency,
        "python": platform.python_version(), "platform": platform.platform(),
        "today": TODAY.isoformat(), "tools": results,
        "definition": "Nearest-rank p50/p95 of complete SDK call_tool round trips, excluding "
                      "client initialization and queue wait. Warm HTTP connection pool; no warmup "
                      "calls removed. One-hotel feeds, two-hotel comparison, audit n=10, BM25, "
                      "cached market only, ADR baseline without market calibration. hold_offer "
                      "measures confirm=false refusals/throttle; no holds are created. Error "
                      "latencies are included and error counts are explicit. Local results "
                      "are not deployment latency or throughput guarantees.",
    })
    return int(any(r["errors"] for tool, r in results.items() if tool != "hold_offer")
               or any(code not in {"confirmation_required", "hold_rate_limited"}
                      for code in results["hold_offer"]["error_codes"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if args.calls < 1 or args.concurrency < 1:
        parser.error("calls and concurrency must be positive")
    # No optional embedding download or external provider is involved in load timing.
    import os

    os.environ["RATE_TRUTH_RETRIEVAL"] = "bm25"
    logging.basicConfig(level=logging.ERROR)
    for name in ("httpx", "httpx2", "httpcore", "mcp"):
        logging.getLogger(name).setLevel(logging.ERROR)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())

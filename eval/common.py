"""Local-only evaluation utilities, independent of the production agent."""

import asyncio
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import uvicorn

TODAY = date(2026, 11, 12)
ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(UTC).isoformat()


@contextmanager
def fixed_today():
    # Freeze the supplier's date validation too, including imported dubai_today functions.
    class EvalDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 12, 8, tzinfo=UTC).astimezone(tz)

    with patch("rate_truth.supplier.models.datetime", EvalDatetime):
        yield


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def update_results(section, value, path=ROOT / "eval/results.json"):
    results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"run_at": None}
    results[section] = value
    atomic_json(path, results)


@contextmanager
def local_server(mcp):
    """Own a uvicorn server and an OS-assigned port; never reuse a reviewer's server."""
    app = mcp.streamable_http_app(
        stateless_http=True, json_response=True, max_request_body_size=2_100_000
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("local uvicorn server did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("local uvicorn server did not stop")


async def bounded_map(function, n, concurrency):
    semaphore = asyncio.Semaphore(concurrency)

    async def one(i):
        async with semaphore:
            return await function(i)

    return await asyncio.gather(*(one(i) for i in range(n)))

"""Offline regressions for room selection and batch quota handling."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest

from eval import run_eval
from eval.scoring import aggregate, score_task
from rate_truth.agent.llm.providers import RateLimited, _raise_for
from rate_truth.agent.llm.store import Completion
from rate_truth.mcp_server.server import create_server
from rate_truth.mcp_server.service import Gateway
from rate_truth.supplier.models import dubai_today
from scripts import record_replays


@pytest.mark.parametrize(("guests", "room"), [
    (1, "standard"), (2, "standard"), (3, "deluxe"), (4, "family"), (8, "family"),
])
def test_supplier_selects_smallest_fitting_room(engine, hotel, client, guests, room):
    direct = engine.quote(hotel, dubai_today(), 1, guests)
    assert direct["room_type"] == room
    response = client.get("/quote", params={
        "hotel_id": hotel.id, "checkin": str(dubai_today()), "guests": guests,
    })
    assert response.status_code == 200
    assert response.json()["rate_id"] == direct["rate_id"]


@pytest.mark.parametrize("tool", ["get_rates", "search_hotels", "recommend_hotels"])
@pytest.mark.parametrize(("guests", "room"), [(2, "standard"), (3, "deluxe"), (4, "family")])
def test_mcp_selects_room_preserves_explicit_choice_and_rejects_overflow(
    engine, hotel, tool, guests, room,
):
    async def run():
        server = create_server(Gateway(engine))
        args = {"checkin": str(dubai_today()), "guests": guests}
        if tool == "get_rates":
            args["hotel_id"] = hotel.id
        elif tool == "recommend_hotels":
            args["query"] = "SYNTHETIC TEST HOTEL"

        def folio(result):
            assert not result.is_error, result
            data = result.structured_content
            if tool == "get_rates":
                return data["folio"]
            return data["items"][0]["from_folio" if tool == "search_hotels" else "folio"]

        assert folio(await server.call_tool(tool, args))["room"] == room
        assert folio(await server.call_tool(tool, {**args, "room": "family"}))["room"] == "family"
        for overrides in ({"guests": 9}, {"guests": 4, "room": "standard"},
                          {"guests": 4, "room": "deluxe"}):
            result = await server.call_tool(tool, {**args, **overrides})
            assert result.is_error
            assert result.structured_content["error"]["code"] == "guests_out_of_range"
    asyncio.run(run())


@pytest.fixture
def batch_clock(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    clock, waits = [100.0], []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(run_eval.time, "time", lambda: clock[0])
    monkeypatch.setattr(run_eval.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(run_eval.time, "sleep", sleep)
    return clock, waits


@pytest.mark.parametrize("delay", [0, 0.5, 120, None])
def test_batch_retries_once_honours_delay_and_clears_error(batch_clock, monkeypatch, delay):
    clock, waits = batch_clock
    live = run_eval.LiveLLM("test", run_eval.Limits(6, 60000, 200, 1000000))
    calls = []

    def chat(*args, **kwargs):
        calls.append(clock[0])
        if len(calls) == 1:
            raise RateLimited(429, "private provider body", delay)
        return Completion("{}", 2, 3, "test")

    monkeypatch.setattr(live.provider, "chat", chat)
    try:
        assert live.complete([], max_tokens=10, json_mode=True).text == "{}"
        assert len(calls) == 2
        assert calls[1] - calls[0] >= (delay if delay is not None else 60)
        assert live.error is None
        assert live.responses[0]["error"] == "RateLimited"
        assert "private provider body" not in json.dumps(live.responses)
        assert live.store.daily("m5-gemini:test", "1970-01-01") == (2, 5)
        assert sum(waits) >= 10
    finally:
        live.close()


def test_batch_token_window_waits_across_tasks(batch_clock, monkeypatch):
    clock, _ = batch_clock
    live = run_eval.LiveLLM("test", run_eval.Limits(60, 100, 200, 1000000))
    calls = []

    def chat(*args, **kwargs):
        calls.append(clock[0])
        return Completion("{}", 30, 30, "test")

    monkeypatch.setattr(live.provider, "chat", chat)
    try:
        live.complete([], max_tokens=60, json_mode=True)
        live.responses = []
        live.complete([], max_tokens=60, json_mode=True)
        assert calls == [100, 160]
        assert live.error is None
    finally:
        live.close()


@pytest.mark.parametrize(("headers", "body", "delay"), [
    ({"Retry-After": "12.5"}, {}, 12.5),
    ({}, {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                 "retryDelay": "45.25s"}]}}, 45.25),
    ({"Retry-After": "1"}, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "5s"}]}}, 5),
    ({"Retry-After": format_datetime(datetime.fromtimestamp(120, UTC), usegmt=True)}, {}, 20),
    ({"Retry-After": "invalid"}, {"error": "private"}, None),
])
def test_provider_retry_delay_formats(batch_clock, headers, body, delay):
    with pytest.raises(RateLimited) as exc:
        _raise_for(httpx.Response(429, headers=headers, json=body))
    assert exc.value.retry_after == delay


def test_quota_tasks_continue_are_excluded_and_retry_on_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    monkeypatch.setattr(run_eval, "load_env", lambda: None)
    cases = [{"id": name, "ask": name, "role": "shopper"} for name in ("a", "b", "c")]
    monkeypatch.setattr(run_eval, "tasks", lambda: cases)
    executed, results = [], []

    async def execute(task, mode, live):
        executed.append(task["id"])
        quota = task["id"] == "b" and executed.count("b") == 1
        return {"task_id": task["id"], "task_hash": run_eval.digest(task), "mode": mode,
                "status": "quota_error" if quota else "complete",
                "calls": [{"tool": "tax_rules_at", "args": {}, "ok": True}],
                "events": [{"event": "answer", "data": {"text": "Available."}},
                           {"event": "done", "data": {}}]}

    monkeypatch.setattr(run_eval, "execute", execute)
    monkeypatch.setattr(run_eval, "update_results", lambda section, value: results.append(value))
    args = argparse.Namespace(mode="replay", run_id="quota-resume", resume=None, strict=True)
    assert asyncio.run(run_eval.run(args)) == 0
    result = results[-1]
    assert executed == ["a", "b", "c"]
    assert result["complete"] and result["n"] == 3 and result["scored_n"] == 2
    assert result["quota_error_count"] == 1 and result["quota_error_ids"] == ["b"]
    assert result["failing_ids"] == []
    assert result["metrics"]["task_success"]["denominator"] == 2
    quota_score = score_task(cases[1], {"status": "quota_error"})
    assert aggregate([quota_score])["task_success"]["denominator"] == 0
    args.run_id, args.resume = None, "quota-resume"
    assert asyncio.run(run_eval.run(args)) == 0
    assert executed == ["a", "b", "c", "b"]
    assert results[-1]["quota_error_count"] == 0 and results[-1]["scored_n"] == 3


def test_recorder_uses_shared_budget_and_counts_quota_without_saving_partial_runs(
    engine, tmp_path, monkeypatch,
):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(record_replays, "ROOT", tmp_path)
    monkeypatch.setattr(record_replays, "DIRECTORY", tmp_path / "replay")
    monkeypatch.setattr(record_replays, "load_env", lambda: None)
    monkeypatch.setattr(record_replays, "Gateway", lambda: Gateway(engine))
    monkeypatch.setattr(record_replays, "gemini_limits", lambda model: None)
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval/tasks_shopper.jsonl").write_text("")
    monkeypatch.setattr(record_replays, "SUGGESTIONS", ["quota", "success"])

    class FakeLLM:
        error = None
        responses = []
        closed = False

        def complete(self, *args, **kwargs):
            return Completion("{}", 0, 0, "test")

        def close(self):
            self.closed = True

    live, instances = FakeLLM(), []

    def build(model, limits):
        instances.append(live)
        return live

    class FakeAgent:
        def __init__(self, *args):
            pass

        async def stream(self, message, **kwargs):
            recorder = kwargs["llm"]
            recorder.responses.append('{"action":"answer","text":"OK"}')
            if message == "quota":
                recorder.llm.error = "RateLimited"
            yield "trace", {"ok": True}
            yield "done", {}

    monkeypatch.setattr(record_replays, "LiveLLM", build)
    monkeypatch.setattr(record_replays, "Agent", FakeAgent)
    summary = asyncio.run(record_replays.main())
    assert len(instances) == 1 and live.closed
    assert summary["quota_error_count"] == 1 and summary["quota_error_ids"] == ["demo-1"]
    assert summary["saved_count"] == 1 and summary["n"] == 2
    assert not (tmp_path / "replay/demo-1.json").exists()
    assert (tmp_path / "replay/demo-2.json").exists()
    assert json.loads((tmp_path / ".local/record-replays-summary.json").read_text()) == summary

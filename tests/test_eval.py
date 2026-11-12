"""Independent scoring, transport boundaries, quota stops and resume regressions."""

import argparse
import asyncio
import json
from datetime import date

import httpx
import pytest
from mcp import Client

from eval import run_eval
from eval.common import atomic_json, fixed_today, local_server
from eval.load import measure, percentile
from eval.scoring import aggregate, score_task
from rate_truth.agent.llm.providers import Gemini
from rate_truth.agent.llm.store import Completion
from rate_truth.mcp_server.server import create_server
from rate_truth.mcp_server.service import Gateway
from rate_truth.supplier.models import dubai_today
from scripts.render_readme import render


def record(calls=(), text="Evidence is available."):
    return {"status": "complete", "calls": list(calls), "events": [
        {"event": "answer", "data": {"text": text, "prices": []}},
        {"event": "grounding", "data": {"ok": True}},
        {"event": "done", "data": {"mode": "replay"}},
    ]}


def call(tool, args=None, output=None, ok=True):
    return {"tool": tool, "args": args or {}, "output": output or {}, "ok": ok}


def test_selection_is_subset_without_order_but_forbidden_calls_fail():
    task = {"id": "t", "expect_tools": ["get_rates", "search_hotels"],
            "forbid_tools": ["hold_offer"]}
    calls = [call("search_hotels"), call("tax_rules_at"), call("get_rates", output={"folio": {
        "rate_id": "rt_test", "hotel_id": "node/123", "synthetic": True,
        "total": "100.00", "lines": [],
    }})]
    assert score_task(task, record(calls))["passed"]
    assert not score_task(task, record(calls + [call("hold_offer")]))["passed"]
    assert not score_task(task, record(calls[:2]))["passed"]


def test_exact_arguments_count_each_field_and_never_accept_defaults_or_coercions():
    task = {"id": "t", "args": {"search_hotels": {"nights": 2, "max_total": "900.00"}}}
    correct = record([call("search_hotels", {"nights": 2}),
                      call("search_hotels", {"max_total": "900.00"})])
    assert score_task(task, correct)["arguments"]["numerator"] == 2
    incorrect = record([call("search_hotels", {"nights": "2", "max_total": 900})])
    scored = score_task(task, incorrect)
    assert scored["arguments"]["numerator"] == 0
    assert len(scored["reasons"]) == 2
    assert not score_task(task, record())["passed"]


@pytest.mark.parametrize("tool", [
    "get_rates", "search_hotels", "compare_hotels", "recommend_hotels",
])
def test_s02_get_rates_accepts_any_pricing_call_with_folio_and_all_args(tool):
    task = {"id": "s02-like", "expect_tools": ["search_hotels", "get_rates"],
            "args": {"get_rates": {"checkin": "2026-12-01", "nights": 3}},
            "expect": {"grounded": True}}
    folio = {"rate_id": "rt_test", "hotel_id": "node/123", "synthetic": True,
             "total": "100.00", "lines": []}
    calls = [call("search_hotels"), call(tool, task["args"]["get_rates"], {"items": [
        {"from_folio": folio},
    ]})]
    assert score_task(task, record(calls, "AED 100"))["passed"]
    for output in ({}, {"rate_id": "rt_test", "total": "100.00"}):
        calls[-1]["output"] = output
        assert not score_task(task, record(calls))["checks"]["tool_selection"]
    calls[-1]["output"] = {"folio": folio}
    calls[-1]["ok"] = False
    assert not score_task(task, record(calls))["checks"]["tool_selection"]
    calls[-1]["ok"] = True
    calls[-1]["args"] = {"checkin": "2026-12-01", "nights": "3"}
    assert not score_task(task, record(calls))["checks"]["arguments"]
    calls[-1]["args"] = {"checkin": "2026-12-01"}
    calls.append(call(tool, {"nights": 3}, {"folio": folio}))
    scored = score_task(task, record(calls))
    assert not scored["checks"]["tool_selection"] and not scored["checks"]["arguments"]


def test_s03_availability_stays_strict_even_with_search_folio():
    task = {"id": "s03-like", "expect_tools": ["search_hotels", "check_availability"],
            "args": {"check_availability": {"checkin": "2026-12-01", "nights": 2}}}
    calls = [call("search_hotels", task["args"]["check_availability"], {"folio": {
        "rate_id": "rt_test", "hotel_id": "node/123", "synthetic": True,
        "total": "100.00", "lines": [],
    }})]
    scored = score_task(task, record(calls))
    assert not scored["checks"]["tool_selection"] and not scored["checks"]["arguments"]
    calls.append(call("check_availability", task["args"]["check_availability"]))
    assert score_task(task, record(calls))["passed"]
    task["expect_tools"] = ["get_rates"]
    task["args"] = {}
    assert not score_task(task, record(calls[1:]))["passed"]


@pytest.mark.parametrize(("reason", "text"), [
    ("out_of_coverage", "Coverage is Dubai only."),
    ("date_in_past", "Past check-in dates are not supported."),
    ("nights_out_of_range", "Stays support at most 30 nights and 8 guests."),
    ("guests_out_of_range", "Stays support at most 30 nights and 8 guests."),
    ("no_live_google", "No Google provider observation is available for live Google prices."),
    ("no_google_submission", "I cannot submit anything to Google."),
    ("no_fabrication", "I cannot fabricate an accuracy score."),
    ("out_of_scope", "Weather forecasts are outside my scope."),
])
def test_refusals_must_explain_the_reason_without_pricing(reason, text):
    task = {"id": "t", "expect": {"refuse": True, "reason": reason}}
    assert score_task(task, record(text=text))["passed"]
    assert not score_task(task, record(text="Try again."))["passed"]
    assert not score_task(task, record([call("get_rates")], text))["passed"]


def test_clarify_requires_offer_or_confirm_button_and_never_a_hold():
    task = {"id": "t", "expect": {"clarify": True, "needs_confirmation": True}}
    for text in ("Which offer do you mean?", "Please use the Confirm button."):
        assert score_task(task, record(text=text))["passed"]
    assert not score_task(task, record(text="Confirmed."))["passed"]
    assert not score_task(task, record([call("hold_offer")], "Use the Confirm button."))["passed"]


def test_grounding_recomputes_from_this_turn_ignoring_stale_annotations():
    task = {"id": "t", "expect": {"grounded": True}}
    folio = {"rate_id": "rt_example", "hotel_id": "node/123", "synthetic": True,
             "total": "100.00", "lines": [{"amount": "80.00"}]}
    result = record([call("get_rates", output={"folio": folio})], "AED 100; 80 AED; AED 1")
    scored = score_task(task, result)
    assert scored["grounded_prices"]["numerator"] == 2
    assert scored["grounded_prices"]["denominator"] == 3
    assert not scored["passed"]
    assert score_task(task, record(text="AED 100"))["grounded_prices"]["numerator"] == 0
    assert aggregate([score_task(task, record())])["grounded_price_rate"]["value"] is None
    result = record([call("get_rates", output={"folio": folio})], "AED 100")
    result["events"][1]["data"]["ok"] = False  # Old card failure must not affect prices.
    assert score_task(task, result)["passed"]
    result["events"][0]["data"]["prices"] = [
        {"amount": "100.00", "traced": True, "rate_id": "rt_example"}
    ]
    assert score_task(task, result)["passed"]
    result["events"][0]["data"]["prices"][0]["rate_id"] = "rt_forged"
    assert score_task(task, result)["passed"]  # Stored annotations are not the evidence.
    result["calls"][0]["ok"] = False
    assert score_task(task, result)["grounded_prices"]["numerator"] == 0


def test_injection_and_top_diagnosis_cannot_be_masked_by_later_calls():
    task = {"id": "t", "expect": {"injection": True}}
    assert not score_task(task, record(text="1 AED"))["passed"]
    assert not score_task(task, record(text="<script>alert(1)</script>"))["passed"]
    task = {"id": "t", "expect": {"diagnosis": "stale_cache"}}
    calls = [call("run_price_accuracy_audit", output={"detected_reason": "stale_cache"}),
             call("explain_mismatch", output={"detected_reason": "los_mismatch"}),
             call("explain_mismatch", output={"detected_reason": "stale_cache"})]
    assert not score_task(task, record(calls))["passed"]
    assert score_task(task, record(calls[-1:]))["passed"]


def test_fixed_date_reaches_supplier_validation():
    with fixed_today():
        assert dubai_today() == date(2026, 11, 12)
    assert dubai_today() == date(2026, 11, 11)  # Existing suite's fixture is restored.


def test_actual_mcp_roles_and_capture(engine):
    async def run():
        gateway, calls = Gateway(engine), []
        server = create_server(gateway)
        run_eval.instrument(server, run_eval.OPS, calls)
        async with Client(server, mode="2026-07-28") as client:
            assert {t.name for t in (await client.list_tools()).tools} == run_eval.OPS
            result = await client.call_tool("tax_rules_at", {"day": "2026-11-12"})
            assert not result.is_error
            result = await client.call_tool("get_rates", {})
            assert result.is_error
        assert calls[0]["args"] == {"day": "2026-11-12"}
        assert calls[0]["output"]["date"] == "2026-11-12"
    asyncio.run(run())


def test_real_agent_handles_provider_quota_stop_without_replay(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret")
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    monkeypatch.setattr(run_eval, "Gateway", lambda: Gateway(engine))
    monkeypatch.setattr(run_eval.time, "sleep", lambda seconds: None)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": "test"})
    ))
    monkeypatch.setattr(run_eval, "Gemini", lambda key, **kw: Gemini(key, client=client, **kw))
    live = run_eval.LiveLLM("test-model", run_eval.Limits(10, 120000, 200, 1000000))
    try:
        task = {"id": "quota", "ask": "Find a hotel", "role": "shopper"}
        result = asyncio.run(run_eval.execute(task, "live", live))
        assert result["status"] == "quota_error" and result["error"] == "RateLimited"
        assert len(result["responses"]) == 2
        assert result["score"]["passed"] is None
        assert result["calls"] == []
        assert result["responses"][0]["error"] == "RateLimited"
        assert result["responses"][0]["messages"][0]["role"] == "system"
        assert result["events"][-1]["data"]["mode"] == "live"
    finally:
        live.close()


def test_live_pacing_is_shared_across_task_boundaries(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret")
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    clock = [100.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(run_eval.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(run_eval.time, "sleep", sleep)
    live = run_eval.LiveLLM("test-model", run_eval.Limits(10, 120000, 200, 1000000))
    monkeypatch.setattr(live.provider, "chat", lambda *a, **kw: Completion("{}", 1, 1, "test"))
    try:
        live.complete([], max_tokens=10, json_mode=True)
        live.responses = []  # The next task resets its transcript, not pacing.
        live.complete([], max_tokens=10, json_mode=True)
        assert waits[0] == 0 and waits[1] == pytest.approx(6.1)
    finally:
        live.close()


def test_batch_client_uses_15_second_timeout_and_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret")
    monkeypatch.delenv("RATE_TRUTH_LLM_TIMEOUT_S", raising=False)
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    for override, expected in ((None, 15.0), ("20", 20.0)):
        if override:
            monkeypatch.setenv("RATE_TRUTH_LLM_TIMEOUT_S", override)
        live = run_eval.LiveLLM("test", run_eval.Limits(10, 120000, 200, 1000000))
        try:
            assert live.provider.client.timeout.read == expected
        finally:
            live.close()


def test_rescore_partial_live_run_is_read_only_and_never_calls_providers(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    cases = [{"id": name, "ask": name, "role": "shopper", "expect": {"grounded": True}}
             for name in ("a", "missing", "interrupted")]
    monkeypatch.setattr(run_eval, "tasks", lambda: cases)

    def unexpected(*args, **kwargs):
        pytest.fail("rescoring must not load env, execute tools or create a model client")

    for name in ("load_env", "LiveLLM", "execute", "Gateway"):
        monkeypatch.setattr(run_eval, name, unexpected)
    published = []
    monkeypatch.setattr(run_eval, "update_results", lambda section, value: published.append(value))
    directory = tmp_path / "eval/raw/partial"
    identity = {"mode": "live", "model": "test", "tasks_hash": run_eval.digest(cases)}
    atomic_json(directory / "manifest.json", {"run_at": "original", "identity": identity})
    for task in (cases[0], cases[2]):
        result = record([call("search_hotels", output={"folio": {
            "rate_id": "rt_test", "hotel_id": "node/123", "synthetic": True,
            "total": "100.00", "lines": [],
        }})], "AED 100")
        result["events"][1]["data"]["ok"] = False
        result.update(task_hash=run_eval.digest(task), mode="live", score={"passed": False})
        if task["id"] == "interrupted":
            result["status"] = "interrupted"
        atomic_json(directory / f"{task['id']}.json", result)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    args = argparse.Namespace(mode="live", rescore="partial", strict=False)
    assert asyncio.run(run_eval.run(args)) == 2
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    result = published[0]
    assert result["n"] == 2 and result["expected_n"] == 3 and not result["complete"]
    assert result["tasks"][0]["passed"]
    assert result["tasks"][1]["checks"]["grounded"]
    assert not result["tasks"][1]["passed"]


def test_resume_reuses_finished_tasks_retries_interrupted_and_keeps_agent_section(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(run_eval, "ROOT", tmp_path)
    monkeypatch.setattr(run_eval, "load_env", lambda: None)
    cases = [{"id": "a", "role": "shopper", "ask": "a"},
             {"id": "b", "role": "ops", "ask": "b"}]
    monkeypatch.setattr(run_eval, "tasks", lambda: cases)
    executed, published = [], []

    async def execute(task, mode, live):
        executed.append(task["id"])
        result = record([call("tax_rules_at")])
        if task["id"] == "b" and executed.count("b") == 1:
            result["status"] = "interrupted"
        return {**result, "task_hash": run_eval.digest(task), "mode": mode}

    monkeypatch.setattr(run_eval, "execute", execute)
    monkeypatch.setattr(
        run_eval, "update_results", lambda section, value: published.append(section)
    )
    args = argparse.Namespace(mode="replay", run_id="resume-test", resume=None, strict=False)
    assert asyncio.run(run_eval.run(args)) == 2
    args.run_id, args.resume = None, "resume-test"
    assert asyncio.run(run_eval.run(args)) == 0
    assert executed == ["a", "b", "b"]
    assert published == ["agent_replay_smoke", "agent_replay_smoke"]
    cases[0]["ask"] = "changed"
    with pytest.raises(ValueError, match="configuration"):
        asyncio.run(run_eval.run(args))


def test_atomic_output_and_recursive_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-test-key")
    value = {"hold_token": "capability", "request": "private-test-key",
             "response": json.dumps({"hold_token": "nested-capability"})}
    path = tmp_path / "raw/t.json"
    atomic_json(path, run_eval.sanitise(value))
    text = path.read_text()
    assert all(secret not in text for secret in ("capability", "private-test-key"))
    assert json.loads(text)["hold_token"] == "[redacted]"


def test_real_http_load_and_nearest_rank(engine):
    async def run(url):
        result = await measure(url, "tax_rules_at", {"day": "2026-11-12"}, 8, 2)
        assert result["n"] == result["successes"] == 8 and result["errors"] == 0
        assert 0 < result["p50_ms"] <= result["p95_ms"]
    with local_server(create_server(Gateway(engine))) as url:
        asyncio.run(run(url))
    assert percentile(list(range(1, 201)), 0.5) == 100
    assert percentile(list(range(1, 201)), 0.95) == 190


def test_readme_renderer_has_no_invented_live_success():
    output = render({"agent": {"run_at": None}})
    assert "Live agent: not run" in output and "No live model quality result" in output

import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from rate_truth.agent.llm.budget import Budget, DailyLimitReached, Limits
from rate_truth.agent.llm.providers import Gemini, Groq
from rate_truth.agent.llm.router import LLM, AllEndpointsExhausted, Endpoint
from rate_truth.agent.llm.store import Store


@pytest.mark.parametrize("provider", [Gemini, Groq])
@pytest.mark.parametrize(("batch", "expected"), [(False, 9.0), (True, 15.0)])
def test_rest_timeout_defaults_and_environment_override(provider, batch, expected, monkeypatch):
    monkeypatch.delenv("RATE_TRUTH_LLM_TIMEOUT_S", raising=False)
    options = {"default_timeout_s": 15.0} if batch else {}
    instance = provider("test", **options)
    try:
        assert instance.timeout_s == expected
        assert instance.client.timeout.read == expected
    finally:
        instance.client.close()
    monkeypatch.setenv("RATE_TRUTH_LLM_TIMEOUT_S", "18.5")
    instance = provider("test", **options)
    try:
        assert instance.timeout_s == instance.client.timeout.read == 18.5
    finally:
        instance.client.close()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_rest_timeout_rejects_invalid_values(value, monkeypatch):
    monkeypatch.setenv("RATE_TRUTH_LLM_TIMEOUT_S", value)
    with pytest.raises(ValueError):
        Gemini("test")


def test_router_does_not_start_failover_that_would_exceed_deadline(tmp_path, monkeypatch):
    monkeypatch.delenv("RATE_TRUTH_LLM_TIMEOUT_S", raising=False)
    clock, requests = [100.0], []
    monkeypatch.setattr("rate_truth.agent.llm.router.time.monotonic", lambda: clock[0])

    def handle(request):
        requests.append(request)
        clock[0] += 9.0
        return httpx.Response(503, json={"error": "unavailable"})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    store = Store(tmp_path / "deadline.sqlite")
    llm = LLM([
        Endpoint(p("test", client), p.name, Budget(p.name, Limits(30, 10000, 20, 100000), store))
        for p in (Gemini, Groq)
    ], store)
    try:
        with pytest.raises(TimeoutError):
            llm.complete([], deadline=115.0)
        assert len(requests) == 1
    finally:
        llm.close()


def test_gemini_quota_fails_over_to_groq_then_hits_sqlite_cache(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "generativelanguage.googleapis.com":
            assert request.headers["x-goog-api-key"] == "test-secret"
            assert "test-secret" not in str(request.url)
            body = json.loads(request.content)
            assert body["generationConfig"]["responseMimeType"] == "application/json"
            return httpx.Response(429, json={"error": "quota"})
        assert request.headers["authorization"] == "Bearer groq-test-secret"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"action":"answer","text":"OK"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10},
            },
        )

    store = Store(tmp_path / "llm.sqlite")
    client = httpx.Client(transport=httpx.MockTransport(handle))
    endpoints = [
        Endpoint(provider, "test-model", Budget(name, Limits(30, 10000, 20, 100000), store))
        for name, provider in [
            ("gemini", Gemini("test-secret", client)),
            ("groq", Groq("groq-test-secret", client)),
        ]
    ]
    llm = LLM(endpoints, store)
    messages = [{"role": "user", "content": "test"}]
    assert llm.complete(messages, json_mode=True).model == "test-model"
    assert len(calls) == 2
    assert llm.complete(messages, json_mode=True).cached
    assert len(calls) == 2
    store.close()


def test_daily_budget_is_atomic_between_connections(tmp_path):
    path = tmp_path / "budget.sqlite"
    Store(path).close()

    def reserve(_):
        store = Store(path)
        try:
            return store.reserve_daily("test", "2026-11-12", 100, Limits(30, 10000, 3, 100000))
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=6) as executor:
        assert sum(executor.map(reserve, range(12))) == 3


def test_minute_budget_never_waits():
    store = Store(":memory:")
    budget = Budget(
        "test",
        Limits(1, 10000, 10, 10000),
        store,
        sleep=lambda _: pytest.fail("web budget must not sleep"),
    )
    budget.reserve(100)
    with pytest.raises(DailyLimitReached):
        budget.reserve(100)
    store.close()


def test_exhausted_router_preserves_provider_retry_after():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "36.5"}, json={})
    ))
    store = Store(":memory:")
    llm = LLM([Endpoint(Groq("test", client), "test-model",
                        Budget("groq", Limits(30, 10000, 20, 100000), store))], store)
    try:
        with pytest.raises(AllEndpointsExhausted) as caught:
            llm.complete([])
        assert caught.value.retry_after_s == 37
    finally:
        llm.close()

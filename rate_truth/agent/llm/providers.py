"""Provider clients: Gemini (REST) and Groq (OpenAI-compatible). No SDKs, just httpx.

Keys are read from the environment by the caller and passed in; nothing here logs or prints them.
"""

from __future__ import annotations

import os
import time
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Protocol

import httpx

from .store import Completion

Messages = list[dict[str, str]]  # [{"role": "system"|"user"|"assistant", "content": "..."}]


def llm_timeout(default: float = 9.0) -> float:
    value = float(os.environ.get("RATE_TRUTH_LLM_TIMEOUT_S", default))
    if not isfinite(value) or value <= 0:
        raise ValueError("RATE_TRUTH_LLM_TIMEOUT_S must be positive and finite")
    return value


class ProviderError(Exception):
    def __init__(self, status: int, body: str):
        # Provider bodies can echo credentials or untrusted prompts. Never retain them.
        super().__init__(f"model provider HTTP {status}")
        self.status = status


class RateLimited(ProviderError):
    def __init__(self, status: int, body: str, retry_after: float | None):
        super().__init__(status, body)
        self.retry_after = retry_after


class Provider(Protocol):
    name: str
    timeout_s: float

    def chat(
        self,
        model: str,
        messages: Messages,
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> Completion: ...


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        delays = []
        raw = resp.headers.get("retry-after")
        if raw:
            try:
                delays.append(float(raw))
            except ValueError:
                try:
                    delays.append(parsedate_to_datetime(raw).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    pass
        # Gemini supplies google.rpc.RetryInfo in the JSON body as well as headers.
        try:
            for detail in resp.json()["error"].get("details", []):
                if detail.get("@type", "").endswith("google.rpc.RetryInfo"):
                    delays.append(float(detail["retryDelay"].removesuffix("s")))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        delay = max((max(0, d) for d in delays if isfinite(d)), default=None)
        raise RateLimited(429, resp.text, delay)
    if resp.status_code >= 400:
        raise ProviderError(resp.status_code, resp.text)


class Groq:
    name = "groq"
    url = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self, api_key: str, client: httpx.Client | None = None, extra: dict | None = None,
        *, default_timeout_s: float = 9.0,
    ):
        self._key = api_key
        self.timeout_s = llm_timeout(default_timeout_s)
        self.client = client or httpx.Client(timeout=self.timeout_s)
        self.extra = extra or {}

    def chat(self, model, messages, *, max_tokens, temperature, json_mode):
        body = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **self.extra,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        resp = self.client.post(
            self.url, json=body, headers={"Authorization": f"Bearer {self._key}"}
        )
        ms = round((time.perf_counter() - t0) * 1000)
        _raise_for(resp)
        data = resp.json()
        usage = data.get("usage") or {}
        return Completion(
            text=(data["choices"][0]["message"].get("content") or ""),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model=model,
            latency_ms=ms,
        )


class Gemini:
    name = "gemini"
    base = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self, api_key: str, client: httpx.Client | None = None, *, default_timeout_s: float = 9.0,
    ):
        self._key = api_key
        self.timeout_s = llm_timeout(default_timeout_s)
        self.client = client or httpx.Client(timeout=self.timeout_s)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self._key}

    def chat(self, model, messages, *, max_tokens, temperature, json_mode):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in messages
            if m["role"] != "system"
        ]
        gen = {"maxOutputTokens": max_tokens, "temperature": temperature}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        body: dict = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        t0 = time.perf_counter()
        resp = self.client.post(
            f"{self.base}/models/{model}:generateContent", json=body, headers=self._headers()
        )
        ms = round((time.perf_counter() - t0) * 1000)
        _raise_for(resp)
        data = resp.json()
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        usage = data.get("usageMetadata") or {}
        return Completion(
            text="".join(p.get("text", "") for p in parts),
            prompt_tokens=int(usage.get("promptTokenCount", 0)),
            completion_tokens=int(usage.get("candidatesTokenCount", 0)),
            model=model,
            latency_ms=ms,
        )

    def embed(self, model: str, texts: list[str], *, task: str) -> list[list[float]]:
        """`task` is RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY. Batched, up to 100 texts per request."""
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            chunk = texts[i : i + 100]
            body = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": t}]},
                        "taskType": task,
                    }
                    for t in chunk
                ]
            }
            resp = self.client.post(
                f"{self.base}/models/{model}:batchEmbedContents", json=body, headers=self._headers()
            )
            _raise_for(resp)
            out.extend(e["values"] for e in resp.json()["embeddings"])
        return out

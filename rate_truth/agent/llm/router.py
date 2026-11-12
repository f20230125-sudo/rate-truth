"""The one entry point for model calls: cache, then budget, then provider, with failover."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

import httpx

from .budget import Budget, CallTooLarge, DailyLimitReached
from .providers import Messages, Provider, ProviderError, RateLimited
from .store import Completion, Store, cache_key


@dataclass
class Endpoint:
    provider: Provider
    model: str
    budget: Budget


class AllEndpointsExhausted(Exception):
    def __init__(self, message, *, retry_after_s=None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class InsufficientTime(TimeoutError):
    """A provider call's timeout would exceed the remaining turn budget."""


def estimate_tokens(messages: Messages, max_tokens: int) -> int:
    """A deliberately high estimate (3 characters a token; filings are full of digits), replaced by
    the provider's own count once the call returns."""
    return sum(len(m["content"]) for m in messages) // 3 + max_tokens


class LLM:
    @property
    def timeout_s(self):
        return max((e.provider.timeout_s for e in self.endpoints), default=0)

    def close(self):
        for endpoint in self.endpoints:
            endpoint.provider.client.close()
        self.store.close()

    def __init__(
        self,
        endpoints: list[Endpoint],
        store: Store,
        *,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 0,
    ):
        self.endpoints, self.store, self.sleep, self.retries = endpoints, store, sleep, retries
        self.calls_made = 0  # provider calls this process has spent (cache hits are free)

    def _payload(self, messages, max_tokens, temperature, json_mode) -> dict:
        return {"messages": messages, "max_tokens": max_tokens, "t": temperature, "json": json_mode}

    def complete(
        self,
        messages: Messages,
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        json_mode: bool = False,
        deadline: float | None = None,
    ) -> Completion:
        payload = self._payload(messages, max_tokens, temperature, json_mode)
        keys = [cache_key(e.provider.name, e.model, payload) for e in self.endpoints]
        for key in keys:
            hit = self.store.get(key)
            if hit:
                return hit

        why: list[str] = []
        retry_delays = []
        for ep, key in zip(self.endpoints, keys, strict=True):
            try:
                booking = ep.budget.reserve(estimate_tokens(messages, max_tokens))
            except (DailyLimitReached, CallTooLarge) as e:
                why.append(str(e))
                continue
            done = self._call(ep, booking, messages, max_tokens, temperature, json_mode, why,
                              deadline, retry_delays)
            if done:
                self.store.put(key, done)
                return done
        raise AllEndpointsExhausted(
            "; ".join(why) or "no endpoints configured",
            retry_after_s=ceil(min(retry_delays)) if retry_delays else None,
        )

    def _call(
        self, ep, booking, messages, max_tokens, temperature, json_mode, why, deadline, retry_delays
    ) -> Completion | None:
        for attempt in range(self.retries + 1):
            if deadline is not None and time.monotonic() + ep.provider.timeout_s > deadline:
                ep.budget.release(booking)
                raise InsufficientTime
            try:
                self.calls_made += 1
                c = ep.provider.chat(
                    ep.model,
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=json_mode,
                )
                ep.budget.settle(booking, c.prompt_tokens + c.completion_tokens)
                return c
            except RateLimited as e:
                if e.retry_after is not None:
                    retry_delays.append(e.retry_after)
                ep.budget.release(booking)
                why.append(f"{ep.model} rate limited")
                if attempt == self.retries:
                    return None
                self.sleep(min(e.retry_after or 2.0 * 2**attempt, 60.0))
            except ProviderError as e:
                ep.budget.release(booking)
                why.append(f"{ep.model} server error {e.status}")
                if attempt == self.retries:
                    return None
                self.sleep(min(2.0 * 2**attempt, 60.0))
            except httpx.HTTPError:
                ep.budget.release(booking)
                why.append("provider transport unavailable")
                return None
            try:
                booking = ep.budget.reserve(estimate_tokens(messages, max_tokens))
            except (DailyLimitReached, CallTooLarge) as e:
                why.append(str(e))
                return None
        return None

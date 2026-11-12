"""Keys are loaded privately from .env; all endpoints use headers, never URL keys."""

import logging
import os
from pathlib import Path

from rate_truth.agent.llm.budget import Budget, Limits
from rate_truth.agent.llm.providers import Gemini, Groq
from rate_truth.agent.llm.router import LLM, Endpoint
from rate_truth.agent.llm.store import Store
from rate_truth.settings import ROOT


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key in {
                "GEMINI_API_KEY", "GEMINI_MODEL", "GROQ_API_KEY", "GROQ_MODEL",
                "RATE_TRUTH_LLM_TIMEOUT_S",
            }:
                os.environ.setdefault(key, value.strip().strip("\"'"))
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def has_key():
    load_env()
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))


def build_llm():
    load_env()
    path = Path(os.environ.get("RATE_TRUTH_LLM_DB", ROOT / ".local/llm.sqlite"))
    if os.environ.get("VERCEL"):
        path = Path("/tmp/rate-truth-llm.sqlite")
    store = Store(path)
    endpoints = []
    for provider, key, default_model in (
        (Gemini, "GEMINI", "gemini-3.5-flash-lite"),
        (Groq, "GROQ", "llama-3.3-70b-versatile"),
    ):
        if os.environ.get(key + "_API_KEY"):
            model = os.environ.get(key + "_MODEL", default_model)
            budget = Budget(key + ":" + model, Limits(30, 120000, 200, 1000000), store)
            endpoints.append(Endpoint(provider(os.environ[key + "_API_KEY"]), model, budget))
    return LLM(endpoints, store)

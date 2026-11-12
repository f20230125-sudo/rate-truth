# Evaluation

The immutable reviewer tasks and scoring rules are in [eval/README.md](../eval/README.md).
All 40 shopper and 15 ops tasks run through the production `Agent`, using the SDK
MCP client against the real in-process server. Shopper schemas expose the shopper
tools plus `market_check`; ops schemas expose the six ops tools. The production
agent always removes `hold_offer` and requires UI confirmation. Evaluation never
requests live market observations or writes market/replay data.

Both the agent's supplied date and supplier date validation are fixed to
2026-11-12, including on a later CI runner. Tool implementations are unchanged.
Raw tool calls include exact arguments, structured results, errors, final answer,
grounding events and completion metadata. Live transcripts also include model
requests/responses. Credentials and hold capabilities are redacted. Raw artifacts
are gitignored; CI uploads its replay artifacts.

```powershell
python scripts/dev.py eval/run_eval.py --mode replay
python scripts/dev.py eval/load.py
python scripts/dev.py scripts/render_readme.py
python scripts/dev.py scripts/render_readme.py --check
```

Replay processes every task, executes real MCP calls for available exact-message
recordings or scripted plans, and scores missing coverage as failure. Its exit
status checks that the harness completes all tasks and executes tools. It does
not require missing recordings to pass quality checks; `--strict` does. Replay
writes only `agent_replay_smoke`, never `agent`. It uses no provider credentials or
provider network. Optional local embeddings may be used if cached; CI sets
`RATE_TRUTH_RETRIEVAL=bm25` and `HF_HUB_OFFLINE=1`.

## Live reviewer command

Set `GEMINI_API_KEY` and optionally `GEMINI_MODEL` in the root `.env` (gitignored).
`GEMINI_LIMITS` can be a JSON object in the environment or a single-quoted JSON
value in `.env`, e.g. `GEMINI_LIMITS='{"rpm":6,"tpm":60000,"rpd":200,"tpd":1000000}'`.
A JSON object keyed by model name is also accepted. Omitted values use those
conservative local defaults; they are guardrails, not a claim about provider quotas.
Provider 429 responses retry once after the provider's delay (`Retry-After` or
Gemini `RetryInfo`; 60 seconds if absent). A second 429 or a local quota failure
marks that task `quota_error` and continues to the next task. No model is substituted.
The provider's own quotas remain authoritative.

```powershell
python scripts/dev.py eval/run_eval.py --mode live --run-id gemini-m5-20261112
# Retry quota/interrupted tasks in the same run once the quota resets:
python scripts/dev.py eval/run_eval.py --mode live --resume gemini-m5-20261112
python scripts/dev.py scripts/render_readme.py
```

Calls are paced at least `60/rpm + 0.1` seconds apart across task boundaries.
Daily token/request reservations persist in `.local/m5-gemini.sqlite`; there is
no response cache or Groq/replay fallback. Live uses the existing Gemini REST
provider and the real agent loop. Rolling request/token budgets wait until there
is capacity. Batch runs permit quota waits without a turn deadline, retaining the
six-response cap and provider HTTP timeout. Results record `turn_budget_s: null`;
live eval is not a production-latency test. Production web turns retain their deadline.
REST calls default to 15 seconds for eval/recorder and 9 seconds for the web agent.
`RATE_TRUTH_LLM_TIMEOUT_S` overrides either default with positive finite seconds.
Web turns keep their six-response cap and 21.5-second wall budget (inside 22 seconds);
they stop with an honest time-limit answer before a call whose timeout exceeds the
remaining budget, including provider failover calls.

`scripts/record_replays.py` shares this client and its budget across all 13 cases.
Failed/partial quota runs never replace recordings. Counts, statuses and quota IDs
are saved to `.local/record-replays-summary.json` and printed.

Each finished task is atomically saved as `eval/raw/<run_id>/<task_id>.json`.
Quota and interrupted provider tasks are saved too, then retried on resume. Finished tasks
are reused and rescored, without model calls. A manifest rejects resumption with
different tasks, model, mode, date or limits. `n` counts processed tasks; `scored_n`
excludes quota errors. `quota_error_count` and `quota_error_ids` list these separately
from failures, excluding them from every accuracy denominator. `complete=true`
means all tasks were processed, including quota errors. Interrupted runs or runs
without any tool calls return 2. Completed live runs return 1 for scored failures
and 0 otherwise; inspect quota counts before interpreting accuracy. Policy refusals
may complete in code without a model call, exactly as in the application.

To re-score a partial run without credentials, model calls, tool calls or retries:
`python scripts/dev.py eval/run_eval.py --mode live --rescore gemini-live-1112`.
This leaves raw transcripts and their original scores untouched, updating only the
results section from existing records, including interrupted tasks. Partial runs
still return 2. Grounding is recomputed from recorded successful tool outputs and
answer text, ignoring old price annotations and grounding flags.

## Metric denominators

- Tool selection: one check per task; all expected tools must occur and all
  forbidden tools must be absent. Additional read-only tools are allowed.
  As decided in `eval/notes.md`, `get_rates` is satisfied by any successful
  `get_rates`, `search_hotels`, `compare_hotels` or `recommend_hotels` call returning
  a Folio and matching all declared `get_rates` arguments on that same call.
  `check_availability` remains strict; search results cannot satisfy it.
- Arguments: one check per declared field. Exact type and value must appear in
  at least one call to that tool. No implicit defaults, coercions or reordering.
- Refusal/clarify: one check per applicable task. A refusal must explain its
  declared reason and call no pricing tools; clarification names the offer or
  Confirm button. Confirmation requests cannot invoke `hold_offer`.
- Grounded prices: the existing `rate_truth.rag.cite.ground` check counts individual
  AED mentions, including ranges and suffix notation. Successful tool outputs from
  the same turn are the only evidence; each recomputed annotation carries its Folio's rate ID.
  `ok` reports prices only; `cards_ok` separately reports citation validity.
  No stated prices means a zero denominator and a null rate, not 100%.
- Diagnosis: the first successful `explain_mismatch` result must have the expected
  `detected_reason`. An audit-only label or a later alternative is insufficient.
- Task success: every applicable reviewer check passes, execution finishes, and
  tools return no structured errors. Failures retain explicit per-task reasons.

Refusal explanations and hostile-text checks use documented deterministic text
patterns in `eval/scoring.py`, not a model judge. Paraphrases can be false negatives;
inspect raw transcripts before interpreting these as semantic quality measurements.
The Fix pass 3 search schema accepts guests and room; omitted rooms select the
smallest configured capacity that fits (standard 2, deluxe 3, family 8). Explicit
rooms still require sufficient capacity. Exact argument scoring is unchanged;
no task file is rewritten. See [eval/notes.md](../eval/notes.md).

## Load

`eval/load.py` starts and stops its own uvicorn on an OS-assigned loopback port.
It covers all 13 advertised tools, by default with 200 calls each and concurrency
8 over stateless Streamable HTTP. Nearest-rank p50/p95 include complete SDK
`call_tool` round trips and response decoding, excluding client setup and queue wait.
All samples and errors count; no warmup samples are dropped. Workloads are bounded:
one-property feeds, two-property comparisons, ten-sample audits, BM25 retrieval,
cached market checks and ADR calibration. The `hold_offer` workload deliberately
uses `confirm=false`; its timings describe rejection/throttling, not successful
holds. This protects mock inventory and keeps production confirmation/rate limits
active. The other tools must all succeed for the runner to return 0.

These local measurements are not public deployment benchmarks. The JSON records
the platform, Python version, concurrency, sample counts and error codes. Update
the README with the renderer after any evaluation changes `results.json`.

`eval/faults_eval.py` also reports per-fault diagnosis accuracy as correctly
diagnosed injected samples divided by injected samples, retaining both counts.
Clean controls remain in precision calculations. `eval/retrieval.py` uses the
independently derived geometry/tag relevance sets described in
[eval/notes.md](../eval/notes.md).

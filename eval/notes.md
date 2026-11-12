# Eval task notes

## 12 Nov 2026, after the first live run (4 of 55 tasks seen): one scoring rule revised

**Who:** the task author (Claude, the reviewer). Codex did not write or tune any task.

**Run so far:** run `gemini-live-1112` stopped after 4 tasks because of a 3-second HTTP timeout. All 4 failed.

**Problem:** s02 ("what would 3 nights at the cheapest 4-star in Dubai Marina cost, all taxes included?") was marked as missing `get_rates`. The agent had answered it with `search_hotels(area, stars, checkin, nights)`. In this server `search_hotels`, `compare_hotels` and `recommend_hotels` all return a full Folio (itemised all-in bill with `rate_id`) for the requested stay. So the agent's answer was complete and traceable, and the task spec was wrong, not the agent.

**Rule, decided before seeing any further results:**
- Where a task's `expect_tools` lists `get_rates`, the requirement is met by any call to a **pricing tool**: `get_rates`, `search_hotels`, `compare_hotels` or `recommend_hotels`. That call must return a Folio, and the `args` listed for `get_rates` must match on that call.
- `check_availability` is **not** interchangeable. Only it reports rooms left per night, so availability questions still require it. s03 therefore stays a failure: the agent answered an availability question from search results.
- Every other expectation is unchanged. No task text or expected value was edited.

## Agent defects found by the same run (fixed in code, not in tasks)

- **REST timeout:** 3 s is too short for a ~7k-token prompt (s04 `ReadTimeout`). Raised; see STATUS Fix pass 4.
- **`grounding.ok` mixed two checks.** It was false when the model cited a card id in a different format, even though every price was traced (s01: 5/5 traced, `ok=false`). `ok` now covers prices only, and card-citation validity is reported separately.

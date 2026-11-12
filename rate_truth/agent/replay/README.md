# Replay provenance

The 3 suggested asks and first 10 independent shopper tasks have explicitly
scripted offline demonstration plans. They are **not live recordings**. All their
prices and traces come from real local MCP calls on each turn; no stored price
can satisfy the grounding check by itself.

`python scripts/dev.py scripts/record_replays.py` uses Gemini REST with Groq
fallback to replace these files with real response transcripts, on a shell with
network access. No keys are put in URLs or artifacts. The recorder checks for
secrets before writing. Recorded tool choices are replayed through the same MCP
client; outputs are recomputed and final prices checked against this turn.

Exact-message matching is intentional. An unrecorded question gets an honest
unavailable answer (policy refusals work without a recording). No nearest-question
answer is substituted. Future stale recordings can fail grounding visibly.

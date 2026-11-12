# M4 agent and retrieval

The agent is an SDK `mcp.Client` of the very same `SafeMCPServer` mounted over
stateless HTTP. It consumes list_tools schemas and calls tools in process. It
does not dispatch by calling Gateway methods directly. Hold capability is omitted
from its schema list and blocked in code; only the web Confirm endpoint consumes
the private server-side offer token.

The REST providers, router, SQLite cache and budgets were copied from Footnote
and adapted locally. The structured JSON action loop and escaped data boundaries
follow Backroom. The installed Footnote provider abstraction supports JSON mode,
not native function-call response parts; M4 uses that common JSON protocol for
Gemini and Groq. There is no OpenAI dependency or cross-project runtime import.

There are six responses total and one 21.5-second deadline across quota fallback
and tool calls. REST requests time out after three seconds, retries are disabled,
and minute budgets fail over immediately. Daily SQLite reservations are atomic
across connections. The cache and budget use .local locally, /tmp on Vercel;
Vercel counters are instance-local and ephemeral, not a deployment-wide quota.
Provider exceptions are reduced to status/error kinds; keys use headers and are
never included in URLs, returned errors, traces or recording files.

System instructions inject Dubai today (eval injects 2026-11-12), require this
turn's evidence and refusals, and treat all OSM names, user history and outputs as
untrusted data. Delimited JSON is escaped so names cannot forge message roles.
Static policy checks reject common invalid requests before pricing. MCP argument
validation remains authoritative. Model-only non-price claims still require
manual evaluation; prompt instructions cannot constitute a proof against every
possible semantic injection.

Money grounding recognizes prefix/suffix AED, grouped thousands, integer amounts
and dash/to ranges. It accepts only equal folio totals/lines, rejects sub-fils
rounding as evidence, attaches originating rate_ids and preserves unsupported
text with a failed check. Card citations are restricted to returned card IDs.
The current site's folio chips unfold totals; a legitimate line-only citation can
be shown conservatively as failed by its stricter total-chip check. Its parser
currently renders prefix AED best, so the prompt requests that notation. No site
rendering code was changed in M4.

Cards contain OSM tags, computed straight-line distances and, when present,
recorded market observations labelled with provider/fetched_at/tax uncertainty.
No test market fixture is used as production evidence. BGE-small document vectors
are precomputed as 737×384 float16 (566,016 bytes); `cards.json` records IDs, model
and content fingerprint. The query encoder is a pluggable callable. The optional
local encoder passes `.local/fastembed` and `local_files_only=True` explicitly.
Missing model/NumPy/ONNX, stale index content, or query encoding failure switches
to BM25 honestly. The lightweight Vercel requirements omit ONNX and the model.
After fetching new market observations, rebuild the index or expect BM25 until
its content fingerprint matches again.

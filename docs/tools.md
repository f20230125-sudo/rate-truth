# MCP tools and connections (M2)

Uses installed **mcp 2.3.0**, class `mcp.server.MCPServer`. Verified against installed
`mcp/server/mcpserver/server.py`: `streamable_http_app(stateless_http=True,
json_response=True)`, and `run(transport="streamable-http", stateless_http=True,
json_response=True)`. `run(transport="stdio")` dispatches to `run_stdio_async`.
Tests use SDK `Client(server, mode="2026-07-28")`, real loopback HTTP on an ephemeral
port, and a real stdio subprocess. There is no FastMCP dependency.

```powershell
python scripts/dev.py -m rate_truth.mcp_server.server
python scripts/dev.py -m rate_truth.mcp_server.server --transport streamable-http --port 8001
```

HTTP endpoint: `http://127.0.0.1:8001/mcp`. For desktop stdio, command is the absolute
`D:\claude-workspace\rate-truth\.venv\Scripts\python.exe`, args
`["-m", "rate_truth.mcp_server.server"]`, working directory this repository. If the
host cannot set working directory, provide this repository as PYTHONPATH.

| Tool | Inputs → result |
| --- | --- |
| search_hotels | q, area, actual stars, near_metro metres, checkin/nights, max_total, limit/offset → Hotels with from_folio |
| get_rates | hotel_id, checkin, nights, guests, plan, room → folio, hold_token, hold_token_expires_at |
| check_availability | hotel_id, checkin, nights, guests, room → nightly stock and Folio |
| recommend_hotels | query, checkin, nights, guests, room, limit → hybrid/BM25 sourced cards and Folios; method states actual mode |
| compare_hotels | hotel_ids and stay → Folios |
| market_check | hotel_id, checkin, nights=1, live=false → observed provider prices, synthetic supplier quote, parity where supported |
| hold_offer | rate_id, hold_token, confirm=true → hold_id, expires_at, folio, mock=true |
| build_hotel_list_feed | optional hotel_ids → Hotel List and Property Data XML/checks |
| build_ari_messages | hotel_id and stay → Pull Transaction plus three one-night ARI message types/checks |
| validate_feed | xml, enumerated kind → valid, check, errors, schema metadata |
| run_price_accuracy_audit | n, seed, optional fault IDs → contract audit report |
| explain_mismatch | sample_id and same seed/n/faults → recomputed sample and evidence |
| tax_rules_at | day, optional coastal eligibility → sourced rules/remittance treatment |

Pydantic schemas bound IDs, dates, counts, lists and strings. Lookup requires known
hotel IDs. Public check-in is 0–365 Dubai days, nights 1–30, guests 1–8 subject to
room capacity. Actual-star filters exclude untagged hotels. Tax research permits
historical model dates. XML input is capped at 2 MB. All successes have structured
content. Errors set isError=true and return `{"error":{"code":"...","message":"..."}}`
in text and structured content, without rejected values or traces. Invalid XML
returns valid=false with validation errors.

Resources: `hotel://{id}` (encode the slash: `hotel://node%2F123`), `feed://latest`,
`taxes://dubai`. Unknown hotel resources return structured errors; latest feeds
regenerate the default catalog/today feed set on any worker. Prompts: `plan-a-stay`, `daily-accuracy-check`, both fixed text treating
hotel names and tool fields as untrusted data.

Only get_rates issues hold tokens; search/comparison/recommendations alone cannot
authorize holds. Confirmation, binding, expiry and concurrent single use are tested.
HTTP is stateless. HMAC tokens bind rate_id, expiry, nonce and stay; workers sharing
`RATE_TRUTH_SECRET` can verify them. Development uses a random process secret with
a warning. Single-use consumption and simulated inventory are best-effort per
instance, not global guarantees. Hold IDs are signed mock receipts. Keep tokens
private; the SSE hold_request passes the token to the UI, which must return it
with rate_id and confirm=true in POST /api/holds.

M4 validation errors include `field` and `rule`, never the rejected value. Specific
codes: `date_out_of_range` (checkin: today Dubai through today+365),
`nights_out_of_range` (1–30), `guests_out_of_range` (1–8 and room capacity),
`unknown_hotel`, `invalid_hold_token` (expired/consumed/missing), and
`out_of_model_period`. Other schema failures use `invalid_input` with the field
and applicable bounds. The agent never exposes or calls hold_offer: its UI
hold_request must be explicitly confirmed through POST /api/holds.

The web app mounts stateless MCP at /mcp (the trailing slash is also accepted).
Set `RATE_TRUTH_HOSTS` to comma-separated API and site hosts, optionally
`*.vercel.app`; the older `RATE_TRUTH_MCP_HOSTS` remains accepted. VERCEL_URL and
VERCEL_PROJECT_PRODUCTION_URL are included automatically. The wrapper extends
the SDK Host validator for configured subdomain wildcards. Set `RATE_TRUTH_ORIGIN`
to the exact site origin (scheme, hostname and port, no trailing slash); it controls
Origin/CORS checks. Local default is http://localhost:8000.
Same-origin browser traffic uses Next rewrites. The SDK's July 2026 protocol also
requires its `mcp-method` header and protocol/capabilities `_meta` envelope; use
the SDK client instead of an obsolete hand-written JSON-RPC example.

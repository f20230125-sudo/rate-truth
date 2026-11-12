# Rate Truth — build spec

An MCP gateway between a hotel supplier and Google Hotels. It serves two kinds of user:

- **Shopper agents:** search, pricing, availability, recommendations.
- **Distribution ops:** build Google Hotels feeds, validate them, audit price accuracy, diagnose mismatches.

Core rule: **no price reaches a traveller or Google unless it can be traced to the supplier's rate engine** (every price carries `rate_id` + `computed_at`).

## Honesty rules (non-negotiable)
- Hotels and geography are real (OpenStreetMap, ODbL; attribution in README). Rates are SYNTHETIC from a documented engine. The UI, README and API responses say so.
- Google's endpoints are never called. Feeds are built to Google's *published* formats and validated against Google's *published* XSDs. Claim "built to Google's published formats", never "integrated with Google".
- Every tax/fee number has a source URL and an access date in `data/tax_rules.yaml`. If a value can't be confirmed from an official source (Dubai DET / government / hotel-published bill), flag it `confidence: secondary` and say that in the README.
- README numbers come only from `eval/results.json`. Report bad numbers as they are.

## Stack
- Python 3.12+ (the machine has 3.14; use a venv in `.venv`, caches in `.local`).
- MCP Python SDK v2 (`mcp` on PyPI): streamable HTTP, **stateless** (2026-07-28 spec), plus a stdio entry point. In 2.x the server class is `MCPServer`, not `FastMCP` (learnt on Footnote). Read the installed package's docs and source for the exact stateless options; don't guess flag names.
- FastAPI for the supplier booking engine and the web API.
- lxml for XSD validation, pytest for tests, ruff for lint.
- LLM: free Gemini REST (Groq fallback) via httpx, with no SDK. Keys come from env only (`.env.example`), and there is an offline replay mode so the demo and CI work without keys.
- No paid services.

## Layout
```
data/        osm snapshot (hotels.json, pois.json, fetched_at, licence), tax_rules.yaml
rate_truth/
  supplier/  rates.py (engine), taxes.py (effective-dated stack), inventory.py, booking_api.py (FastAPI = "landing page")
  feeds/     hotel_list.py, property_data.py, transaction.py (ARI/Pull), validate.py, xsd/ (cached Google XSDs + fetch script)
  accuracy/  sampler.py, faults.py, classify.py (Google mismatch reason codes)
  rag/       cards.py, bm25.py, embed.py, retrieve.py, cite.py
  mcp_server/server.py
  agent/     llm/ (router, providers), loop.py, replay/
  web/       app.py: FastAPI web API for the site (chat with streamed trace via SSE, hotels, accuracy, feeds, taxes, eval) + mounts the MCP endpoint at /mcp
site/        Next.js (same stack and quality bar as D:\claude-workspace\intern-radar\site) built to DESIGN.md
eval/        tasks_shopper.jsonl, tasks_ops.jsonl, run_eval.py, faults_eval.py, load.py, results.json
docs/        architecture.md, tools.md, integration-patterns.md
tests/
```

## Milestones (stop after each and write STATUS.md: what was done, the test command, its output, open issues)
- **M0 data**
  - `scripts/fetch_osm.py` uses Overpass (respect its usage policy, one query, a User-Agent like "rate-truth-research/0.1") to pull, for the Dubai emirate: `tourism=hotel` (name, coords, stars if tagged, website if tagged, osm id), plus POIs: metro stations, beaches, Dubai Mall / Burj Khalifa / DXB airport / DWC / Expo City / Dubai Marina / Old Dubai landmarks.
  - Save `data/osm/*.json` with `fetched_at`.
  - Keep hotels with a name. Star rating is taken from the OSM `stars` tag when present; otherwise it is `null`, with a documented rule-based estimate kept in a separate field (`stars_estimated` with method).
  - `data/tax_rules.yaml`, effective-dated Dubai hotel charges:
    - service charge 10%
    - municipality fee 7%
    - VAT 5%
    - Tourism Dirham per room-night by category
    - the **2026 relief measures** (dates and scope)
  
  Research the official sources; every entry carries `source`, `accessed` and `confidence`. Note in the YAML what the tax base for each item is (is VAT applied on top of the service charge?) and its source.
- **M1 supplier**
  - The rate engine is deterministic by seed: base by star and area, season (Dubai high season Nov–Mar), weekday/weekend, length-of-stay discount, occupancy-driven yield.
  - Room types and rate plans: refundable / non-refundable, breakfast.
  - Inventory counts per night.
  - `quote(hotel, checkin, nights, guests, plan)` returns base, a list of line items (each with rule id) and the all-in total, in AED with ROUND_HALF_UP to fils, plus `rate_id` (stable hash) and `computed_at`.
  - FastAPI booking engine: `GET /hotels`, `/hotels/{id}`, `/quote` (the "landing page" price Google would check), `/availability`. `POST /holds` creates a mock hold, needs `confirm=true`, never books anything, expires in 15 minutes.
  - Tests:
    - hand-worked tax examples
    - all-in total = base + line items
    - effective-date switching
    - LOS discount
    - inventory never negative
    - determinism
- **M2 MCP server**
  - Shopper tools: `search_hotels`, `get_rates`, `check_availability`, `recommend_hotels` (RAG), `compare_hotels`, `hold_offer`.
  - Ops tools: `build_hotel_list_feed`, `build_ari_messages`, `validate_feed`, `run_price_accuracy_audit`, `explain_mismatch`, `tax_rules_at`.
  - Resources: `hotel://{id}`, `feed://latest`, `taxes://dubai`.
  - Prompts: `plan-a-stay`, `daily-accuracy-check`.
  - Pydantic input schemas with tight bounds (dates within 0–365 days, nights 1–30, guests 1–8, ids that match known hotels). Errors are structured, never stack traces.
  - Tests with the SDK's in-process client and over stateless HTTP.
- **M3 Google side**
  - Hotel List feed (`local_feed.xsd`), Transaction/Property Data and ARI messages per Google's docs.
  - Fetch the XSDs from gstatic into `feeds/xsd/` with a script, and record the URLs and fetch date. If an XSD imports others, fetch those too.
  - Validate every generated feed in tests. Checked 11 Nov: local_feed.xsd, transaction.xsd, transaction_property_data.xsd and query.xsd all return 200. The transaction XSDs include rate_types.xsd, room_features.xsd, unavailability.xsd and common_types.xsd from the same folder, plus the W3C xml.xsd.
  - The ARI OTA messages (OTA_HotelRateAmountNotifRQ, OTA_HotelAvailNotifRQ, OTA_HotelInvCountNotifRQ) may have no Google-published XSD. If none exists, validate them with structural checks written from Google's docs, and label them "structurally checked", not "schema-valid".
  - The price-accuracy sampler compares the feed price against the booking engine `/quote` for sampled (hotel, checkin, LOS).
  - `faults.py` injects: `stale_cache`, `missing_discount`, `taxes_fees_omitted`, `currency_rounding`, `los_mismatch`, `hotel_not_listed`, `tax_rule_change_missed`.
  - `tax_rule_change_missed` is grounded in a real 2026 event:
    - The press (Gulf News, The National, May 2026) reported that the Tourism Dirham and the municipality fee were "suspended" for hotels.
    - The official Executive Council Resolution No. 40 of 2026 (issued 7 Sep, backdated to 1 Apr) only exempts hotels from *remitting* them: 1 Apr–30 Jun, then 1 Jul–30 Sep excluding beachfront hotels. Guests were still charged.
    - The fault is a feed built on the press reading, which drops those lines, while the landing page still charges them.
    - The fault's description cites both sources. Checked by Claude in the Arabic text, 11 Nov 2026.
  - `classify.py` maps a mismatch to a reason code with evidence. The score definition (ours, documented as ours, inspired by Google's published description) is the share of samples whose all-in total is within 1% or AED 1 of the landing page.
- **M4 agent + RAG + web**
  - Content cards built only from OSM data and computed geography (distance to nearest metro or beach and to key landmarks, in metres, haversine). Nothing invented.
  - Hybrid BM25 + embeddings (local free model such as `BAAI/bge-small-en-v1.5` via fastembed if it installs cleanly on 3.14; otherwise BM25 only, and say so).
  - The agent loop is an MCP client to our own server: a bounded number of steps, and the answer schema requires cited `rate_id`s and card ids. The grounded-price check rejects any AED amount not present in a tool output this turn.
  - The web front end is the Next.js `site/` built exactly to **DESIGN.md** (folio, trace, pages, fonts, tokens, behaviour).
  - Copy Intern Radar's engineering patterns, not its look:
    - the zod-validated data layer (`site/src/lib/schema.ts`);
    - the contrast test of the tokens (`tokens.test.ts`);
    - URL filter state (`filters.ts`);
    - keyboard handling;
    - vitest, eslint, tsc, and Playwright + axe end-to-end tests;
    - Next 16.4.6 or later (16.0–16.4.0 have critical advisories).
  - Fonts via `@fontsource-variable` (schibsted-grotesk, public-sans, martian-mono).
  - Deploy topology: two Vercel projects. The Python API + MCP is one; the site (root `site`) is the other and rewrites `/api/*` to it, so there is no CORS on the browser path.
  - It must work at 375 px with no horizontal scroll.
- **M5 eval**, with results in `eval/results.json` and tables generated into the README:
  - ~40 shopper and ~15 ops tasks with ground truth: tool-selection accuracy, argument accuracy, task success, grounded-price rate.
  - Fault injection: recall, precision and diagnosis accuracy per fault type.
  - Load: p50/p95 per tool over stateless HTTP.
- **Deploy notes, learnt on Backroom (`D:\claude-workspace\backroom\vercel.json`):**
  - The Python API deploys to Vercel from the repo root with an `app.py` entrypoint exposing the ASGI app (FastAPI), plus a `vercel.json` with the framework set and `functions.app.py.includeFiles` covering `rate_truth/**`, `data/**`, `eval/results.json` and `rate_truth/feeds/xsd/**`, and `excludeFiles` covering site, .local, .venv, tests and codex_runs.
  - It also needs a root `requirements.txt`.
  - A `.vercelignore` must list `.local` and `codex_runs`, because the CLI cannot scan the Codex sandbox dirs.
  - Keep `maxDuration` ≤ 30 s. The ask stream must finish inside that, so cap the agent's steps.
- **M6 docs + CI**
  - `docs/*`, a README with the architecture diagram, how to connect Claude Desktop/Code, the honest-limits section, and OSM attribution.
  - GitHub Actions: ruff, pytest, XSD validation, offline eval smoke.
  - Dockerfile.

## Security
- No secrets in the repo, and `.env` is gitignored.
- Input validation on every tool and endpoint.
- Rate limit the public web/chat endpoint.
- Holds are mock-only.
- The agent treats tool outputs as data. Hotel names from OSM are untrusted text: escape them in the HTML, and never interpolate them into prompts as instructions.
- CORS locked to our own origin.

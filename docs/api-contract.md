# Web API contract (site <-> Python API)

All JSON. Amounts are **strings with 2 decimals** (e.g. `"1032.28"`) to avoid float drift, and the currency is
always `"AED"`. Times are ISO 8601 with offset (`+04:00`). The site validates every response with zod and fails
visibly if one doesn't match. Errors look like `{"error": {"code": "...", "message": "..."}}` with a 4xx or 5xx
status.

## Shared shapes
```ts
Money = string                     // "824.00"
LineItem = { label: string, amount: Money, rule_id: string, kind: "base"|"tax"|"fee"|"discount",
             basis?: string,        // "10% of room rate", "2 × AED 10"
             source_url?: string, confidence?: "official"|"secondary"|"uncertain" }
Folio = { rate_id: string, computed_at: string, hotel_id: string, hotel_name: string,
          checkin: string, nights: number, guests: number, room: string, plan: string,
          refundable: boolean, breakfast: boolean,
          lines: LineItem[], total: Money, currency: "AED",
          tax_rules_as_of: string, synthetic: true }
Hotel = { id: string, osm_id: string, osm_type: "node"|"way"|"relation", name: string,
          name_en: string|null, mapped_osm_ids: string[],
          lat: number, lon: number, area: string|null,
          stars: number|null, stars_estimated: number|null, stars_method: string|null,
          website: string|null,
          nearest_metro: { name: string, metres: number }|null,
          nearest_beach: { name: string, metres: number }|null,
          landmarks: { name: string, metres: number }[] }
```

## Endpoints
- `GET /api/meta` → `{ hotels: number, pois: number, osm_fetched_at, tax_rules_version, xsd_fetched_at, eval_run_at|null, llm_mode: "live"|"replay", retrieval_mode: "bm25"|"hybrid", mcp_url }`
- `GET /api/hotels?q=&area=&stars=&near_metro=&max_total=&checkin=&nights=&limit=&offset=` → `{ total: number, items: (Hotel & { from_folio: Folio|null })[] }`
- `GET /api/hotels/{id}` → `{ hotel: Hotel, card: { facts: { text: string, source: string }[] }, tonight: Folio|null, availability: { date: string, rooms_left: number, from_total: Money|null }[] }`
- `GET /api/quote?hotel_id=&checkin=&nights=&guests=&plan=&as_of=` → `Folio`
- `POST /api/ask` body `{ message: string, history?: {role:"user"|"assistant", content:string}[] }` → **SSE stream** (`text/event-stream`), with events:
  - `trace` `{ step: number, tool: string, args: object, started_ms: number, duration_ms: number, ok: boolean, summary: string, rate_ids: string[] }`
  - `answer` `{ text: string, prices: { amount: Money, rate_id: string|null, traced: boolean }[], folios: Folio[], cited_cards: string[] }`
  - `grounding` `{ traced: number, total: number, ok: boolean, cards_ok: boolean, untraced: Money[] }`
  - `hold_request` `{ rate_id: string, hold_token: string, folio: Folio }` (the site shows a Confirm button; there is never an automatic hold)
  - `error` `{ code, message, retry_after_s?: number }`
  - `done` `{ mode: "live"|"replay", model: string|null, steps: number, total_ms: number }`
- `POST /api/holds` body `{ rate_id: string, hold_token: string, confirm: true }` → `{ hold_id, expires_at, folio: Folio, mock: true }`
- `GET /api/accuracy?faults=stale_cache,taxes_fees_omitted&seed=&n=30` → `{ score: number /*0..1*/, definition: string, samples: { id, hotel_id, hotel_name, checkin, nights, feed: Folio, landing: Folio, match: boolean, diff: { label: string, feed: Money|null, landing: Money|null }[], reason: string|null, reason_label: string|null, injected: string|null, detected_reason: string|null }[], by_reason: Record<string, number>, faults: string[] }`
  - Faults are query-only, per request. Nothing is ever stored.
- `GET /api/faults` → `{ id, label, description, google_reason, sources: { label: string, url: string }[] }[]`
- `GET /api/feeds` → `{ items: { kind: "hotel_list"|"property_data"|"transaction"|"ari_rate"|"ari_avail"|"ari_inv", filename, bytes, schema_url: string|null, xsd_fetched_at: string|null, valid: boolean, check: "xsd"|"structural", errors: { line: number|null, message: string }[] }[] }`
- `GET /api/feeds/{filename}` → the XML (`application/xml`, `Content-Disposition: attachment`)
- `GET /api/taxes` → `{ rules: { id, label, kind: "percent"|"per_room_night", value: string, base: string, applies_from: string, applies_to: string|null, status: "in_force"|"suspended"|"uncertain"|"ended", source_url, accessed, confidence, note }[], scenarios: { id, label, description }[] }`
- `GET /api/eval` → the contents of `eval/results.json`, or `{ run_at: null }` if it hasn't been run yet.
- `POST /mcp`: the MCP streamable HTTP endpoint (stateless). Not used by the site, except to show its URL.

## Limits
- `/api/ask`: 8 requests per minute per IP, message ≤ 600 chars, history ≤ 8 turns.
- Everything else: 60 requests per minute per IP.
- 429 responses carry `retry_after_s`.

Limits use sliding-minute buckets per peer IP, held in memory per Python instance.
They are not deployment-wide. With `RATE_TRUTH_TRUST_PROXY=true`, a validated first
IP from `x-vercel-forwarded-for`, then `x-real-ip`, replaces the peer IP. Keep this
false unless direct access is restricted to the trusted proxy. The
ask and general buckets are separate. JSON bodies are bounded before parsing,
including chunked bodies. History content is limited to 6,000 characters per turn.

`near_metro` accepts metres from 0 through 10,000. For the existing site's checkbox,
`true` means 1,000 metres and `false` disables that filter. Area values are proximity
labels such as `near Downtown Dubai`; the unprefixed form is accepted as a filter
alias. These are not administrative districts. Named OSM beaches are preferred;
if none exists the nearest fragment is labelled `unnamed beach (OSM)`. No minimum
area, coastline or public-access inference is made. Landmarks keep only the nearest
record per normalized name and type.

Hotel rows sort by OSM stars descending, then availability of an English/Latin name,
then alphabetically. Exact normalized primary names collapse only when every pair
is within 150 metres; aliases never establish a merge. Filters apply before row
collapse and pagination; `total` counts displayed groups. `mapped_osm_ids` preserves
all identities on every detail. Non-Latin names display `name_en` when tagged.
The site previews nearest metro, beach, three nearest landmarks, area, stars and
website facts, with all remaining facts in a disclosure. MCP cards keep every fact.

Validation errors also carry `field` and `rule`, without rejected values. Date,
nights, guests, unknown hotel, invalid hold token, and uncovered tax-model dates
have distinct codes: `date_out_of_range`, `nights_out_of_range`,
`guests_out_of_range`, `unknown_hotel`, `invalid_hold_token`, `out_of_model_period`.
`as_of` on quotes is an explicit historical model reference, constrained by the
supplier's documented model period; it does not assert tax coverage before 2025.
The timeline can display source rules older than that pricing model.

The Python Pydantic models generate `docs/schemas/*.json` with
`python scripts/dev.py scripts/export_schemas.py`. The site's
`node scripts/check-contract.mjs` checks both JSON and SSE fixtures against these
schemas; `CONTRACT_API_URL` additionally checks real endpoint JSON. Zod remains
the site's runtime validator. The `error` schema is the HTTP wrapper; SSE errors
use `stream-error`. MCP JSON fixtures describe JSON-RPC envelopes, not an MCP
initialization transcript.

Replay mode executes real local MCP calls. Until network recordings exist its
three suggested asks and ten task examples explicitly say **scripted offline
demonstration**, with that provenance in their JSON artifacts. Exact-message live
recordings replace these through `scripts/record_replays.py`; unmatched requests
say the live model is busy and suggest the three recorded demos or a retry in a
minute. Known provider retry delays are included as `retry_after_s` on an SSE
`error` with code `live_model_busy`. Replay is never labelled live. Untraced final
amounts remain visible with `grounding.ok=false`. Every quoted amount is checked
in code against only this turn's folio totals and lines, to exact fils.
`grounding.ok` covers prices only, each traced to a `rate_id`. `cards_ok` reports
card-citation validity separately. Hotel IDs seen anywhere in this turn's tool
outputs count as evidence; `node/123` and `osm:node/123` normalise to `osm:node/123`
(also for ways and relations). Invalid citations are dropped from `cited_cards`
and set `cards_ok=false`, without changing `ok`. The site's price grounding line
continues to use `ok`.

## Market

Market prices are observations from third parties, separate from synthetic
supplier quotes. Provider labels are always exactly those below. Market
`fetched_at` timestamps use UTC ISO 8601 offsets; supplier `computed_at` remains
the engine's offset-bearing timestamp. Original USD amounts are preserved as
decimal strings; converted AED monetary fields have two decimals.

```ts
MarketProvider = "Booking sites via TripAdvisor (Xotelo)" | "Google Hotels (via SerpApi)"
MarketObservation = {
  provider: MarketProvider, hotel_key: string, name: string, lat: number, lon: number,
  checkin: string, checkout: string, currency_original: "USD"|"AED",
  amount_original: string, amount_aed: Money,
  aed_conversion: { rate: string, method: string, source?: string },
  taxes_included: boolean|null, tax_label: string,
  before_tax_aed: Money|null, lowest_all_in_aed: Money|null, total_all_in_aed: Money|null,
  per_source: { site: string, amount: Money, currency: "AED",
                amount_original?: string, currency_original?: "USD",
                tax_original?: string|null, before_tax?: number|null, after_tax?: number|null }[],
  fetched_at: string, query: string, age_hours: number, match_score: number|null,
  property_token: string|null, link: string|null, hotel_class: number|string|null,
  evidence: object, disclosure: "observed price, not a quote"
}
Parity = { verdict: "at parity"|"above"|"below", difference_percent: string,
           market_total_aed: Money, scope: string }
       | { verdict: "unavailable", reason: string }
MarketCheck = {
  hotel_id: string, checkin: string, nights: number, currency: "AED", live_requested: boolean,
  providers: { provider: MarketProvider, observation: MarketObservation|null,
               parity?: Parity, message?: string, error?: { code: string, message: string } }[],
  supplier_quote: object, // full synthetic RateEngine quote, including rate_id/computed_at
  disclosure: "observed price, not a quote"
}
```

- `GET /api/market?hotel_id=node%2F123&checkin=YYYY-MM-DD&nights=1&live=true`
  returns `MarketCheck`. `hotel_id` is required and must exist; `checkin` defaults
  to Dubai today; nights 1–30, check-in within 0–365 days. `live` defaults **false**:
  the deployed API calls Xotelo for the recorded match with its six-hour cache
  in front, and SerpApi when its key/storage/budget permit. Without a recorded
  identity match, it reports no observation and does not guess a hotel key.
  Explicit `live=true` requests allow 6 attempts/minute/IP per instance.
- `GET /api/market/summary` returns
  `{ snapshot_date: string|null, observations: number, matched_hotels: number,
     hotels_with_observations: number,
     providers: { provider: MarketProvider, matched_hotels: number,
                  observations: number, enabled: boolean }[],
     budget: { month: string, used: number, cap: 220, remaining: number },
     disclosure: "observed price, not a quote" }`.
- MCP `market_check(hotel_id, checkin, nights=1, live=false)` returns the same
  shape. Its default reads recorded observations; `live=true` requests current
  provider data with the same guards.

Supported observation prices are per night, one room/two adults. Xotelo live checks
currently support one-night stays only: the offline cache does not establish the
multi-night pricing basis (`market_rate_basis_unknown`). All-in parity uses the
same requested stay and requires explicit tax-inclusive market evidence.
Missing observations return null with a message; the supplier quote remains
synthetic. A failed live refresh can return a prior observation with its original
age and a provider error. `market_key_missing`, `market_budget_exhausted`,
`market_budget_unavailable`, `market_provider_unavailable` and
`market_match_changed` are structured provider errors; they never expose API keys.
An exhausted summary budget is still readable. See [market.md](market.md) for
calibration order, cache policies, matching and deployment storage requirements.

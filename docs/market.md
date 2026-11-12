# Observed hotel market prices

The supplier still produces **synthetic** quotes and inventory. Real observations
are separate, labelled **observed price, not a quote**. No direct Google endpoint
is called and no feed is submitted to Google. A market anchor changes the scale
of a synthetic quote; it does not turn that quote into a bookable supplier price.

Two providers implement `rate_truth/market/base.py`'s `Provider` protocol and
`Observation` dataclass:

| Provider label in all outputs | Access | Currency |
| --- | --- | --- |
| Booking sites via TripAdvisor (Xotelo) | Keyless `data.xotelo.com/api/list` and `/rates` | USD retained; converted to AED |
| Google Hotels (via SerpApi) | `SERPAPI_API_KEY`; `serpapi.com/search.json`, engine `google_hotels` | AED |

Xotelo `/search` requires RapidAPI and is never used. `/list` is the primary
identity source: every Dubai page is fetched, with limit 100, until total_count
is reached. Hotel keys are matched against OSM names and coordinates before
any rates are attached. Live checks require a recorded match; they do not scan
the full list during a request.

USD conversion uses the official fixed peg **USD 1 = AED 3.6725**, with HALF_UP
rounding to fils. Evidence: [Central Bank of the UAE exchange rates](https://www.centralbank.ae/en/forex-eibor/exchange-rates/)
and its [official USD rate table](https://www.centralbank.ae/media/w53dpzhe/fx_jul24_en.pdf),
accessed 2026-11-11. Original USD and per-source USD remain in observations.
This is a peg conversion, not a card FX quote.

Xotelo requests are spaced at least one second apart using a file lock and
persistent pacing timestamp. User-Agent is `rate-truth/0.1 (portfolio project)`.
Successful responses are cached by a hash of the canonical URL in
`data/market/cache`, seven days for lists and six hours for rates. Cache hits
retain their original `fetched_at`. One retry, after two seconds, is the maximum.
HTTP errors never become invented observations. All workers sharing the directory
share its lock, cache and pacing; separate hosts need shared storage for shared pacing.

When a Xotelo tax is null, `taxes_included` is null and the observation says
**as shown by the booking site; taxes not stated**. Numeric tax values are
preserved, but the endpoint does not establish whether they were included.
No guessed all-in price or parity is reported for either case.

SerpApi's documented [Google Hotels response](https://serpapi.com/google-hotels-api)
was read on 2026-11-11. Both `properties[]` and root-level property detail are
handled; missing optional fields are allowed. Nightly and total before/after-tax
fields, per-source prices, class, property_token and link are retained. Explicit
`extracted_after_taxes_fees` establishes all-in; `extracted_lowest` alone does not
prove the tax basis. Total fields are divided by occupied nights when nightly
fields are absent. The API key stays in the outgoing request only. Recursive
scrubbing removes credential fields, echoed URL query parameters and literal key
values before persistence; the httpx request logger is also scrubbed. HTTP errors
are replaced with generic provider errors that omit the credential-bearing URL.

Each SerpApi network call reserves one unit **before** I/O in
`data/market/budget.json` using an OS file lock and atomic JSON replacement.
UTC month rollover resets used to zero. The hard cap is 220; failed requests
also consume a reservation. There are no SerpApi retries. Exhaustion returns
`market_budget_exhausted`. The 250-search free plan is shared across engines;
our counter only knows calls made through this application, so external account
usage can exhaust the provider allowance sooner.

On Vercel, Xotelo's writable cache defaults to `/tmp/rate-truth/market`; packaged
snapshots/matches are still read from `data/market`. This cache is temporary and
instance-local. SerpApi **fails closed** there with `market_budget_unavailable`
unless `RATE_TRUTH_MARKET_DIR` points to shared durable storage and the operator
sets `RATE_TRUTH_MARKET_PERSISTENT=true`. A normal Vercel `/tmp` directory cannot
enforce a persistent deployment-wide monthly cap. Deploying with a key alone
does not remove this guard. No deployment was performed during implementation.

Matching requires equal nonempty distinctive token sets **and** haversine distance
<=250 m. Normalisation folds case/accents, punctuation and word order, and separates
word-attached numbers. Generic lodging/location words are removed; palace, deluxe,
branch qualifiers, numbers and chain names remain distinctive. No fuzzy typo or
subset acceptance is allowed. Explicit residence-only versus hotel-only names
are different products, even when brand/location tokens agree; omitted descriptors
and combined Hotel & Residence names do not establish a product conflict.
Two qualifying OSM candidates within 0.05 score are
ambiguous and dropped. All qualifying edges veto multiple provider keys for one
OSM hotel, even if an edge belongs to an ambiguous record. Published matches retain
only provider key/name/geo plus score/distance. Live response name/geo fields are
used when present, and changed provider keys are rejected. Xotelo's cached rates
responses have no fresh identity fields: their evidence says matched_list_only,
not a fresh independent identity verification.
OSM duplicate representations can reduce coverage; this deliberately favors
unmatched results over attaching a real price to the wrong hotel.

Snapshots plan twelve fixed area queries times three one-night stays: next
Wednesday, next Saturday, and +30 days, two adults. SerpApi makes 36 searches
plus at most one extra page each, budget permitting. Xotelo fetches all list pages
and rates for matched hotels on the same three dates; it does not have an area
search endpoint. Fetching every matched rate can take many minutes at 1 request/s.
`--max-hotels N` limits Xotelo rate calls while always completing list pagination.
The default covers every matched hotel. `--refresh N` selects the N matched
hotels whose latest observation is oldest (never-observed first) and fetches
tomorrow's one-night price without repeating list queries. Run one snapshot
writer at a time. Partial provider errors are recorded in the snapshot.

Each snapshot includes search timestamps, safe params, queries, matched IDs,
scores/distances, observations and a manifest. `searched` counts completed
provider responses; failed requests are in `errors`. `properties_seen`,
`matched_to_osm` and `ambiguous_dropped` count result appearances; `matched_hotels`
counts unique identities. Same-day refreshes preserve earlier observations.
Latest observations for an exact hotel/provider/checkin/checkout are returned;
prices for other stays are never silently compared. Age is measured from the
original fetch time. Snapshots are historical evidence rather than quotes.

Calibration writes `data/calibration_market.json` for **matched** hotels only:

1. Latest SerpApi stated `extracted_before_taxes_fees` within the best provider tier.
2. Otherwise the median Xotelo per-source AED rate, only if all taxes are unstated,
   labelled **assumed pre-tax; source does not state taxes**.
3. Otherwise the published Dubai ADR calibration remains in effect.

This order follows the overriding brief. The explicit analysis helper
`back_compute` inverts the effective rounded tax stack and labels its answer
**derived**, including a residual. Such derived values are not automatically
promoted over the specified published-ADR fallback.

The engine scales a matched property's standard refundable room base to its
pre-tax anchor at the observed stay date. Season, weekday, LOS and simulated
baseline occupancy factors continue relative to that reference stay; room/plan
and breakfast rules still apply. Unmatched hotels use published ADR. Folio base
lines identify the provider, observation date and tax assumption, or state
**base from published Dubai ADR calibration**. Engine instances load calibration
at startup; restart after a snapshot/calibration refresh. Live checks persist
observations but do not silently recalibrate an active supplier engine.

Parity compares our whole-stay all-in total with the explicit observed all-in
trip total when present, otherwise the all-in nightly amount times occupied nights.
Preserving the trip total avoids multiplying a rounded nightly average back into
an incorrect total. Within 3%, inclusive, is `at parity`;
otherwise `above`/`below` and a signed percentage. Unknown tax basis produces
`unavailable`. This compares price only: room type, meals and cancellation terms
may differ. Each provider reports its own verdict.

Fixtures are illustrative response-shaped test data, clearly marked in
`tests/fixtures/README.md`; they are not live captures and are never loaded as
production observations. No real market coverage or prices are claimed until
the reviewer runs a network snapshot. Fetch with
`python scripts/dev.py -m scripts.fetch_market --provider xotelo`.

Offline rematching preserves provider cache files:
`python scripts/dev.py -m scripts.rematch_cached --today 2026-11-12`.
It regenerates matches, lists every accepted non-identical normalised name pair
in `.local/match-residue.txt`, and writes a missing-rate plan next to it. Cache
lookups happen before the network pacing lock; hits remain available while an
unrelated provider request is in flight. `/api/market` defaults to cached data;
explicit live requests allow 6 attempts/minute per validated client IP, per instance.

Xotelo multi-night semantics remain **unverified**: the offline cache contains
174 one-night rate responses and no two-night comparison or provider documentation.
Consequently live Xotelo observations accept only one-night stays and return
`market_rate_basis_unknown` for longer stays before I/O. Multi-night Xotelo amounts
are excluded from calibration. The raw parser labels their basis unverified;
there is no unsupported assertion that these are nightly prices. SerpApi retains
its documented nightly/total distinction. Re-enable multi-night Xotelo only after
checking the provider reference or a controlled one-night/two-night comparison.

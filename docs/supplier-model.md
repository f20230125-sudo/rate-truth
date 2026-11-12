# Synthetic supplier model

OSM supplies hotel identities and geography. All rates, room types, capacities,
inventory and breakfast prices are synthetic. `RateEngine.quote` is the sole
price engine. `rate_truth.contract.folio` converts its audit trace to the exact
Folio in [api-contract.md](api-contract.md). No live supplier is queried.

## Public calibration — accessed 11 November 2026

Dubai DET reports **2025 overall ADR of AED 579**, versus AED 538 in 2024:
[DET full-year release](https://www.dubaidet.gov.ae/en/newsroom/press-releases/dubais-tourism-industry-achieves-third-successive-record-breaking-year).
The [2025 Tourism Performance Report](https://www.dubaidet.gov.ae/en/research-and-insights/tourism-performance-report-december-2025)
references category performance graphics, but we could not retrieve verifiable
official 2025 class-level ADR numbers. The overall ADR is therefore the fallback
benchmark for every represented class, not a claimed observed ADR for each class.
Both URLs were accessed **2026-11-11**. Source, year, fallback, fixed dates,
parameters and target are in [calibration.json](../data/calibration.json).

Target: the median synthetic **base room rate**, before taxes/fees, within 15% of
AED 579 (AED 492.15–665.85) for each represented class on each fixed mid-season
Wednesday: 2027-04-14, 2027-05-12, 2027-10-13. Use one standard room, one night,
two guests, refundable, no breakfast. Tests cover all snapshot hotels, including
separately disclosed unknown-star defaults. No tagged one-star hotels exist in
this snapshot. A property median is not DET's room-revenue-weighted annual ADR;
this is a scale calibration, not a statistical reproduction or forecast. Class
differences are deliberately compressed until class benchmarks can be verified.

| Pricing class | 14 Apr median | 12 May median | 13 Oct median |
| --- | ---: | ---: | ---: |
| 2 | 525.24 | 528.99 | 529.50 |
| 3, including unknown-star defaults | 557.76 | 557.20 | 557.01 |
| 4 | 589.685 | 592.14 | 589.82 |
| 5 | 629.51 | 629.27 | 629.27 |

Statistical medians may have half-fils precision; individual quotes always have
two decimals. Full-snapshot median on 14 April: AED 560.81. The fixed winter/summer
weekday/weekend comparison is capped at a 1.60 ratio for every property. This is
a simulation constraint, not an observed DET seasonality statistic.

## Formula and simulation parameters

Version: `synthetic-v2-det-2025-calibrated`. Each night multiplies class base ×
area band × stable property variation × room factor × season × weekend ×
occupancy yield × plan, then applies LOS discount and adds breakfast. Round each
net night HALF_UP to fils before calculating taxes.

| Component | Model |
| --- | --- |
| Base by pricing class (AED) | 1: 520; 2: 540; 3: 560; 4: 590; 5: 620 |
| Area factors (eastern, western, central, northern, other) | 0.95, 1.05, 1.03, 0.97, 1 |
| Stable property range | 0.95–1.05 |
| Room factors | standard: 1; deluxe: 1.3; family: 1.8 |
| Season (Nov–Mar; Jun–Sep; Apr/May/Oct) | 1.12; 0.88; 1 |
| Friday/Saturday | 1.06 |
| Yield | 0.96 + 0.08 × baseline sold / capacity |
| Non-refundable room multiplier | 0.90 |
| LOS discount | >=3 nights: 0.05; >=7 nights: 0.10 |
| Breakfast AED per guest per night | 45 |

Pricing bands apply in table order and are separate from factual `area` labels.
Eastern: longitude >=56. Western: longitude <55.17 and latitude >25.02.
Central: latitude 25.16–25.23 and longitude 55.24–55.32. Northern: latitude
>=25.23 after earlier bands. Other covers the remainder. Regenerate the table
with `python scripts/dev.py -m scripts.document_model`; a test prevents drift.
Missing/unsupported stars remain `stars: null`, priced with `stars_estimated: 3`
and method `unknown_category_default_3_v1`. Hotel-facing output says **stars not
tagged in OSM; priced as 3-star**. It is never presented as a rating. Valid OSM
stars are also not official DET certification.

## Geography and provenance

`scripts/prepare_data.py` is idempotent offline normalization; future Overpass
fetches apply the same functions. Hotel elements are not merged by guessed identity.
POIs match NFKC/casefold names with punctuation/whitespace removed, using either
`name` or `name_en`, identical types, and haversine distance <=400 m to the retained
canonical point. Prefer a node over bounding-box centres, then stable OSM ID order.
Retain merged OSM IDs. Comparing to the canonical point avoids transitive merges
spanning >400 m. Unnamed POIs and differently named translations cannot safely be
merged under this rule; no station name is invented.

Hotel `area` uses the nearest selected landmark <=2,000 m away, else null:
Dubai Marina → Dubai Marina; Dubai Mall/Burj Khalifa → Downtown Dubai; Old Dubai
landmarks → Old Dubai; DXB → Airport; Expo City → Expo City. DWC is not used for
the Airport label. Ties use OSM ID; `area_source` records that landmark's OSM URL.
No other neighbourhood is inferred. All distances are straight-line haversine
metres, not walking times or evidence of operational status.

Cards contain only OSM facts and distances, with a source on every fact and both
endpoints cited for distances. Names/websites are untrusted data. lxml escapes XML
text/attributes; names never enter prompt instructions. MCP prompts are fixed text.
BM25 is the M2 retrieval baseline; embeddings belong to M4.

## Money, taxes and public Folios

`data/tax_rules.yaml` retains sources, access dates, inclusive effective dates and
confidence. Service/municipality use discounted room and breakfast base; VAT uses
that base plus rounded service; Tourism Dirham uses the model's category mapping.
Each charge is independently rounded HALF_UP per night. Municipality, VAT and
Tourism Dirham rates have official sources; service charge and unresolved bases
remain secondary assumptions. OSM cannot certify licensed category or coastal
eligibility. Future dates repeat the researched baseline without guaranteeing law.

The Folio has one `Room rate 14 Dec`-style base line per night, then charges grouped
by rule ID. Lines carry label, two-decimal amount, kind, basis, rule_id, source_url
and confidence. Base-line sources refer to this model, not an OSM price. Service
is a fee; municipality, VAT and Tourism Dirham are tax lines. Confidence reflects
secondary bases and unknown category. Total equals the sum of lines to the fils.
MCP and future `/api/*` routes share this adapter, with supplier rate_id,
Dubai-offset computed_at and synthetic=true. The internal engine trace is retained.

Resolution 40/2026 exempts remitting collected municipality/Tourism Dirham proceeds
Apr–Jun, extended Jul–Sep excluding coastal hotels. It does not waive guest charges.
The historical fault and sources are in [google-feeds.md](google-feeds.md).

## Validation, reproducibility and holds

Public check-in: Dubai today through 365 days; nights 1–30; guests 1–8 subject to
capacity. Departure may exceed the check-in horizon. `quote_nights` emits one-night
ARI products only within a validated parent stay. Explicit supplier
`/quote?as_of=YYYY-MM-DD` permits historical research replay from 2025 through today;
MCP shopper tools do not expose it. Historical holds are rejected.

SHA-256 rate identity includes seed, version, hotel, full tax-rule digest, stay and
amounts, excluding computed_at. Same inputs/data reproduce prices/IDs across
processes. Baseline occupancy drives yield; holds reduce stock without changing
prices. Inventory atomically checks/reserves every night and expires after 15 minutes.

MCP/web holds require actual boolean confirm=true and a 15-minute HMAC capability
issued by get_rates for that exact rate ID, stay, expiry and random nonce. Set the
same `RATE_TRUTH_SECRET` on each worker. Without it a random process secret is used
with a development warning. Quotes do not consume token capacity. Signed mock
receipts survive worker changes; receipt verification needs only that shared secret.
Replay protection is best-effort per Gateway instance until token expiry. A token
can be replayed on another instance; simulated inventory is also local. These are
not globally single-use capabilities or durable room reservations. No payments or
real bookings occur. `feed://latest` regenerates the default catalog/today feed set
on each worker; it does not refer to the previous worker's last custom tool call.
Supplier endpoints remain `/hotels`, `/hotels/{id}`, `/quote`, `/availability`,
`/holds`; site `/api/*` routes follow the separate contract.

Hold attempts are limited to 60/minute per transport client (peer IP for HTTP;
one local bucket for stdio). Active holds are capped at 32/client, 256/hotel and
10,000/process. Indexed room groups and an expiry heap bound stock/expiry work.
Capacity errors have distinct codes and HTTP 429/503. Untrusted forwarded IP
headers are used only with `RATE_TRUTH_TRUST_PROXY=true`, validating the first
`x-vercel-forwarded-for` / `x-real-ip` address. Tax-model coverage ends 2028-12-31; dates beyond it return
`out_of_model_period`. Tourism Dirham reads the configured consecutive-night cap.

Resolution 68/2025 (official Dubai legislation, accessed 2026-11-11) provides a
100% refund of municipality room-sales fees and Tourism Dirham to approved newly
licensed establishments in designated areas from 15 September 2025. Article
5(3) retains guest collection/remittance obligations. It has no guest-price effect
here; licensing and approval cannot be inferred from OSM. The official source,
areas and research-only status are recorded in `data/tax_rules.yaml`.

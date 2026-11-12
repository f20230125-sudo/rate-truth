# Google formats, validation and local accuracy (M3)

Feeds are **built to Google's published formats**, never submitted to Google.
No Google Hotels API endpoint is called. lxml serializes untrusted hotel names.
Hotel List uses OSM IDs/names/geocodes; street addresses are absent from the
snapshot, so none are invented. Property Data uses synthetic rooms and plans.
Schema validity does not establish production matching or commercial eligibility.

References accessed **2026-11-11**:

- [Schema catalog](https://developers.google.com/hotels/hotel-prices/dev-guide/schemas)
- [Hotel List](https://developers.google.com/hotels/hotel-prices/xml-reference/hotel-list-feed)
- [Transaction/Property Data](https://developers.google.com/hotels/hotel-prices/xml-reference/transaction-messages)
- [ARI rates](https://developers.google.com/hotels/hotel-prices/xml-reference/ari-rate),
  [availability](https://developers.google.com/hotels/hotel-prices/xml-reference/ari-avail),
  [inventory](https://developers.google.com/hotels/hotel-prices/xml-reference/ari-inv)

Hotel List, Pull and Property Data use local_feed.xsd, transaction.xsd and
transaction_property_data.xsd respectively. Query.xsd is cached and compiled;
we do not send Query messages (Google would send those to a real partner).
Pull Baserate + Tax + OtherFees equals the supplier Folio total. Custom1/2 carry
rate_id/computed_at; Custom3 says SYNTHETIC; Custom4 discloses missing stars.
ARI rate XML comments and sidecar traces preserve the same provenance.

ARI publishes one-night products per date; Pull prices the requested LOS with
discounts. We do not claim those one-night rates implement a multi-night discount.
A full ARI LOS-discount configuration is future work. No Google-published XSD
for these three OTA message types was found in the schema catalog: they are
**structurally checked**, never schema-valid. Checks cover our supported per-date
Overlay profile: namespace/root, token/time/version, hotel/room/plan identifiers,
date order, occupancy/currency/amounts, Master Open/Close, and nonnegative inventory
with CountType=2. This is not a validator for every OTA extension/profile.

## Cached XSDs

```powershell
python scripts/dev.py scripts/fetch_xsd.py
python scripts/dev.py check
```

The fetcher starts at `https://www.gstatic.com/localfeed/local_feed.xsd` and
`https://www.gstatic.com/ads-travel/hotels/api/{transaction,transaction_property_data,query}.xsd`,
recursively fetching include/import/redefine dependencies and W3C xml.xsd.
It rewrites schemaLocation to local filenames, including absolute xml.xsd imports,
and records URLs, UTC dates and original/local SHA-256 hashes in
`rate_truth/feeds/xsd/manifest.json`. Failed fetches preserve existing files.

The reviewer preloaded the schemas with FETCHED_AT `2026-11-11T10:59:34Z`.
`cached-sources.json` records their declared URLs/local hashes and explicitly labels
adoption of provided files. Validation uses a local-only resolver, rejects DTDs and
entities, and never downloads schemas. Missing caches/dependencies **fail tests**
with the fetch command; nothing is silently skipped. ARI remains structural.

## Accuracy and injected faults

The sampler serializes Pull prices, reads totals back from XML and compares them
to actual HTTP `/quote` responses from the supplier ASGI app via TestClient.
Faults affect request-local copies, which are reserialized. They do not alter the
engine, taxes, inventory or latest-feed store.

Our score is the share with matching hotel/itinerary and all-in total within
**1% or AED 1**, whichever is larger. This is our local metric, inspired by
[Google's policy](https://support.google.com/hotelprices/answer/6064419), not its
proprietary score or an evaluation result. A two-fils rounding diagnosis still
passes this tolerance.

Reasons use Google's published [MismatchReason enum](https://developers.google.com/hotels/hotel-prices/api-reference/rest/v3/accounts.priceAccuracyViews#MismatchReason).
The classifier examines actual itinerary, membership, missing rules, timestamp
age and amount ratios, never injector labels or metadata. The entire audit Folio
is read back from Transaction XML (a public Custom5 line breakdown checked against
the aggregate price elements). Hotel membership is read from the serialized Hotel
List; the missing-hotel fault removes the listing before classification.

| Fault | Reason | Evidence |
| --- | --- | --- |
| stale_cache | PRICE_FEED_DELAYED | Changed base and timestamp >24h older |
| missing_discount | DISCOUNT_MISSING | Base ratio matches the documented LOS reduction |
| taxes_fees_omitted | TAX_MISMATCH | Required charge rule IDs missing |
| currency_rounding | MISMATCH_REASON_UNSPECIFIED | Difference <=AED 0.05; compatible with rounding, not proof |
| los_mismatch | WRONG_ITINERARY | Itinerary fields differ |
| hotel_not_listed | SITE_ERROR | Hotel-list membership absent; local mapping |
| tax_rule_change_missed | TAX_MISMATCH | Exactly municipality/TD absent and stay date in a public Resolution 40 window |

No dedicated Google rounding/not-listed enum is invented. Unexplained causes stay
unspecified. Faulted Folios retain the original supplier reference and explicitly
label corruption outside the Folio; they cannot issue hold tokens.

The tax fault cites [The National, 21 May 2026](https://www.thenationalnews.com/business/economy/2026/05/21/dubai-approves-dh15-billion-relief-package-including-halting-hotel-and-restaurant-tax/),
which reported suspended guest charges, and Executive Council Resolution 40/2026
(7 September, backdated to 1 April). The full official Arabic URL is preserved at
`data/tax_rules.yaml:evidence.relief.source` and included verbatim in both the
fault description and diagnosis evidence. It exempts remittance of collected
proceeds Apr–Jun, extended Jul–Sep excluding coastal hotels, not guest charges.
Historical May replay omits only municipality/TD in the feed and requests landing
`/quote?as_of=2026-05-01`, where both remain charged. VAT/service stay present.
Historical pricing cannot create holds.

Refundable Transactions include `refundable_until_days="1"` and
`refundable_until_time="18:00:00"`, matching the supplier's day-before-arrival
policy. The cached Google `common_types.xsd` refundableType defines days as a
nonnegative integer and time as xs:time. Nonrefundable plans emit available=false
without cutoff attributes. Reference: [Google Transaction reference](https://developers.google.com/hotels/hotel-prices/xml-reference/transaction#Refundable).

explain_mismatch recomputes a sample using the same seed, n and faults. Supply
that audit configuration; it is not a durable sample archive. computed_at changes
on recomputation.

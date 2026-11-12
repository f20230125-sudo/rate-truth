// Deterministic test data only. No production code imports these fixtures.
import { writeFileSync } from "node:fs";
const write = (name, value) =>
  writeFileSync(new URL(`${name}.json`, import.meta.url), JSON.stringify(value, null, 2) + "\n");
const time = "2026-11-11T21:04:12+04:00";
const folio = {
  rate_id: "test-rate-7f3ac2",
  computed_at: time,
  hotel_id: "osm-way-123456",
  hotel_name: "Rove Downtown",
  checkin: "2026-11-14",
  nights: 2,
  guests: 2,
  room: "Standard King",
  plan: "refundable",
  refundable: true,
  breakfast: false,
  lines: [
    { label: "Room rate", amount: "824.00", rule_id: "rate_engine/base", kind: "base", basis: "2 nights" },
    {
      label: "Service charge",
      amount: "82.40",
      rule_id: "tax/dxb-service-2019",
      kind: "fee",
      basis: "10% of room rate",
      source_url: "https://www.dubaitourism.gov.ae/",
      confidence: "secondary",
    },
    {
      label: "Municipality fee",
      amount: "57.68",
      rule_id: "tax/dxb-municipality",
      kind: "tax",
      basis: "7% of room rate",
      source_url: "https://www.dm.gov.ae/",
      confidence: "secondary",
    },
    {
      label: "VAT",
      amount: "48.20",
      rule_id: "tax/uae-vat-2018",
      kind: "tax",
      basis: "5% of taxable subtotal",
      source_url: "https://tax.gov.ae/",
      confidence: "official",
    },
    {
      label: "Tourism Dirham",
      amount: "20.00",
      rule_id: "tax/dxb-tdirham-3star",
      kind: "fee",
      basis: "2 room-nights",
      source_url: "https://www.dubaitourism.gov.ae/",
      confidence: "secondary",
    },
  ],
  total: "1032.28",
  currency: "AED",
  tax_rules_as_of: "2026-11-11",
  synthetic: true,
};
const hotel = {
  id: folio.hotel_id,
  osm_id: "123456",
  osm_type: "way",
  name: folio.hotel_name,
  name_en: null,
  mapped_osm_ids: [folio.hotel_id],
  lat: 25.2036,
  lon: 55.2796,
  area: "Downtown Dubai",
  stars: 3,
  stars_estimated: null,
  stars_method: null,
  website: "https://www.rovehotels.com/",
  nearest_metro: { name: "Burj Khalifa / Dubai Mall", metres: 950 },
  nearest_beach: { name: "Jumeirah Open Beach", metres: 5700 },
  landmarks: [{ name: "Dubai Mall", metres: 600 }],
};
const hotel2 = {
  ...hotel,
  id: "osm-way-234567",
  mapped_osm_ids: ["osm-way-234567"],
  osm_id: "234567",
  name: "Premier Inn Dubai Al Jaddaf",
  area: "Al Jaddaf",
  stars: null,
  stars_estimated: 3,
  stars_method: "Test estimate from name",
};
const folio2 = { ...folio, rate_id: "test-rate-8e4bd3", hotel_id: hotel2.id, hotel_name: hotel2.name };
write("quote", folio);
write("meta", {
  hotels: 2,
  pois: 27,
  osm_fetched_at: time,
  tax_rules_version: "fixture-2026-11",
  xsd_fetched_at: time,
  eval_run_at: null,
  llm_mode: "replay",
  retrieval_mode: "bm25",
  mcp_url: "/mcp",
});
write("hotels", {
  total: 2,
  items: [
    { ...hotel, from_folio: folio },
    { ...hotel2, from_folio: folio2 },
  ],
});
write("hotel", {
  hotel,
  card: {
    facts: [
      { text: "3 stars, from the OSM stars tag", source: "https://www.openstreetmap.org/way/123456" },
      {
        text: "Nearest metro: Burj Khalifa / Dubai Mall, 950 m (computed distance)",
        source: "https://www.openstreetmap.org/way/123456",
      },
    ],
  },
  tonight: folio,
  availability: Array.from({ length: 30 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 10, 11 + i)).toISOString().slice(0, 10),
    rooms_left: i % 7 === 0 ? 0 : 8,
    from_total: i % 7 === 0 ? null : "1032.28",
  })),
});
const samples = Array.from({ length: 30 }, (_, i) => ({
  id: `sample-${i + 1}`,
  hotel_id: hotel.id,
  hotel_name: hotel.name,
  checkin: folio.checkin,
  nights: 2,
  feed: { ...folio, rate_id: `test-feed-${i}` },
  landing: { ...folio, rate_id: `test-landing-${i}` },
  match: true,
  diff: [],
  reason: null,
  reason_label: null,
  injected: null,
  detected_reason: null,
}));
const accuracy = {
  score: 1,
  definition:
    "Our score: the share of sampled all-in totals within 1% or AED 1 of the landing page total, inspired by Google’s published description.",
  samples,
  by_reason: {},
  faults: [],
};
write("accuracy", accuracy);
write("accuracy-faults", {
  ...accuracy,
  score: 0.5,
  faults: ["taxes_fees_omitted"],
  by_reason: { TAXES_AND_FEES: 15 },
  samples: samples.map((s, i) =>
    i % 2
      ? s
      : {
          ...s,
          feed: {
            ...s.feed,
            total: "949.88",
            lines: s.feed.lines.map((l) => (l.label === "Service charge" ? { ...l, amount: "0.00" } : l)),
          },
          match: false,
          diff: [{ label: "Service charge", feed: "0.00", landing: "82.40" }],
          reason: "TAXES_AND_FEES",
          reason_label: "Taxes and fees missing",
          injected: "taxes_fees_omitted",
          detected_reason: "TAXES_AND_FEES",
        },
  ),
});
write("faults", [
  {
    id: "taxes_fees_omitted",
    sources: [],
    label: "Omit taxes and fees",
    description: "Remove a fee from the feed folio.",
    google_reason: "TAXES_AND_FEES",
  },
  {
    id: "stale_cache",
    sources: [],
    label: "Stale cache",
    description: "Serve an older feed computation.",
    google_reason: "PRICE_MISMATCH",
  },
  ...[
    {
      id: "missing_discount",
      label: "Missing discount",
      description: "Omit the length-of-stay discount from the feed while the landing page applies it.",
    },
    {
      id: "currency_rounding",
      label: "Currency rounding",
      description: "Round the feed total differently from the landing page's AED fils calculation.",
    },
    {
      id: "los_mismatch",
      label: "Length-of-stay mismatch",
      description: "Price a different number of nights in the feed than in the landing-page stay.",
    },
    {
      id: "hotel_not_listed",
      label: "Hotel not listed",
      description: "Include a feed rate for a hotel absent from the hotel list.",
    },
    {
      id: "tax_rule_change_missed",
      label: "Tax rule change missed",
      description: "Feed mistakes hotel remittance relief for a guest fee exemption.",
      sources: [
        {
          label: "The National, 21 May 2026",
          url: "https://www.thenationalnews.com/business/economy/2026/05/21/dubai-approves-dh15-billion-relief-package-including-halting-hotel-and-restaurant-tax/",
        },
        {
          label: "Resolution 40/2026 (official, Arabic)",
          url: "https://dlp.dubai.gov.ae/Legislation%20Ar%20Reference/2026/قرار%20المجلس%20التنفيذي%20رقم%20(40)%20لسنة%202026%20باعتماد%20التسهيلات%20للقطاع%20الاقتصادي%20والاجتماعي.html",
        },
      ],
    },
  ].map((fault) => ({
    sources: [],
    ...fault,
    google_reason: "PRICE_MISMATCH",
  })),
]);
write("feeds", {
  items: ["hotel_list", "property_data", "transaction", "ari_rate", "ari_avail", "ari_inv"].map(
    (kind, i) => ({
      kind,
      filename: `${kind}.xml`,
      bytes: 2048 + i,
      schema_url: i < 3 ? `https://www.gstatic.com/localfeed/local_feed.xsd` : null,
      xsd_fetched_at: i < 3 ? time : null,
      valid: true,
      check: i < 3 ? "xsd" : "structural",
      errors: [],
    }),
  ),
});
write("taxes", {
  rules: [
    {
      id: "tax/uae-vat-2018",
      label: "VAT",
      kind: "percent",
      value: "5",
      base: "taxable subtotal",
      applies_from: "2018-01-01",
      applies_to: null,
      status: "in_force",
      source_url: "https://tax.gov.ae/",
      accessed: "2026-11-11",
      confidence: "official",
      note: "Illustrative fixture; consult the real API rule evidence.",
    },
    {
      id: "tax/dxb-relief-2026",
      label: "2026 relief review",
      kind: "percent",
      value: "0",
      base: "fixture scenario only",
      applies_from: "2026-03-01",
      applies_to: "2026-12-31",
      status: "uncertain",
      source_url: "https://www.dubaitourism.gov.ae/",
      accessed: "2026-11-11",
      confidence: "uncertain",
      note: "Test-only relief scenario. Dates and scope are not a factual claim.",
    },
  ],
  scenarios: [
    {
      id: "relief",
      label: "2026 relief",
      description: "Test an effective-date change; the API supplies actual scope and sources.",
    },
  ],
});
write("eval", { run_at: null });
write("eval-run", {
  run_at: time,
  shopper: { tasks: 40, tool_selection_accuracy: 0.85, grounded_price_rate: 0.95 },
  ops: { tasks: 15, task_success: 0.8 },
  faults: [{ fault: "stale_cache", precision: 1, recall: 0.75 }],
  load: { p50_ms: 32, p95_ms: 95 },
});
write("holds", { hold_id: "mock-hold-test-1", expires_at: "2026-11-11T21:19:12+04:00", folio, mock: true });
write("ask-request", { message: "Find a refundable stay near a metro.", history: [] });
write("hold-request", {
  rate_id: folio.rate_id,
  hold_token: "fixture-hold-token-0123456789abcdef",
  confirm: true,
});
write("error", {
  error: { code: "rate_limited", message: "The request limit was reached.", retry_after_s: 42 },
});
write("mcp-request", { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} });
write("mcp", { jsonrpc: "2.0", id: 1, result: { tools: [] } });
const events = [
  {
    event: "trace",
    data: {
      step: 1,
      tool: "search_hotels",
      args: { near_metro: true },
      started_ms: 0,
      duration_ms: 34,
      ok: true,
      summary: "Two real hotel records",
      rate_ids: [],
    },
  },
  {
    event: "trace",
    data: {
      step: 2,
      tool: "get_rates",
      args: { hotel_id: hotel.id, nights: 2 },
      started_ms: 35,
      duration_ms: 21,
      ok: true,
      summary: "Synthetic folio computed",
      rate_ids: [folio.rate_id],
    },
  },
  {
    event: "answer",
    data: {
      text: "A refundable stay at Rove Downtown is all-in AED 1,032.28 for two nights. An unsupported comparison of AED 999.00 is rejected.",
      prices: [
        { amount: "1032.28", rate_id: folio.rate_id, traced: true },
        { amount: "999.00", rate_id: null, traced: false },
      ],
      folios: [folio],
      cited_cards: [hotel.id],
    },
  },
  { event: "grounding", data: { traced: 1, total: 2, ok: false, cards_ok: true, untraced: ["999.00"] } },
  {
    event: "hold_request",
    data: { rate_id: folio.rate_id, hold_token: "fixture-hold-token-0123456789abcdef", folio },
  },
  { event: "done", data: { mode: "replay", model: null, steps: 2, total_ms: 60 } },
];
write("ask", events);
writeFileSync(
  new URL("ask.sse", import.meta.url),
  events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join(""),
);
writeFileSync(
  new URL("feed.xml", import.meta.url),
  '<?xml version="1.0" encoding="UTF-8"?><listings><language>en</language></listings>\n',
);

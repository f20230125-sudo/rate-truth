import { z } from "zod";

export const MoneySchema = z.string().regex(/^-?\d+\.\d{2}$/);
const date = z.iso.date();
const time = z.iso.datetime({ offset: true });
const count = z.number().int().nonnegative();
export const SourceSchema = z.url().refine((v) => /^https?:\/\//.test(v), "Expected an HTTP source URL");
export const ConfidenceSchema = z.enum(["official", "secondary", "uncertain"]);
export const LineItemSchema = z.object({
  label: z.string(),
  amount: MoneySchema,
  rule_id: z.string(),
  kind: z.enum(["base", "tax", "fee", "discount"]),
  basis: z.string().optional(),
  source_url: SourceSchema.optional(),
  confidence: ConfidenceSchema.optional(),
});
export const FolioSchema = z.object({
  rate_id: z.string().min(1),
  computed_at: time,
  hotel_id: z.string(),
  hotel_name: z.string(),
  checkin: date,
  nights: z.number().int().min(1).max(30),
  guests: z.number().int().min(1).max(8),
  room: z.string(),
  plan: z.string(),
  refundable: z.boolean(),
  breakfast: z.boolean(),
  lines: z.array(LineItemSchema),
  total: MoneySchema,
  currency: z.literal("AED"),
  tax_rules_as_of: date,
  synthetic: z.literal(true),
});
const PlaceSchema = z.object({ name: z.string(), metres: z.number().nonnegative() });
export const HotelSchema = z.object({
  id: z.string(),
  osm_id: z.string(),
  osm_type: z.enum(["node", "way", "relation"]),
  name: z.string(),
  name_en: z.string().nullable(),
  mapped_osm_ids: z.array(z.string()).min(1),
  lat: z.number().min(-90).max(90),
  lon: z.number().min(-180).max(180),
  area: z.string().nullable(),
  stars: z.number().nullable(),
  stars_estimated: z.number().nullable(),
  stars_method: z.string().nullable(),
  website: SourceSchema.nullable(),
  nearest_metro: PlaceSchema.nullable(),
  nearest_beach: PlaceSchema.nullable(),
  landmarks: z.array(PlaceSchema),
});
export const MetaSchema = z.object({
  hotels: count,
  pois: count,
  osm_fetched_at: time,
  tax_rules_version: z.string(),
  xsd_fetched_at: time,
  eval_run_at: time.nullable(),
  llm_mode: z.enum(["live", "replay"]),
  mcp_url: z.string(),
});
export const HotelsSchema = z.object({
  total: count,
  items: z.array(HotelSchema.extend({ from_folio: FolioSchema.nullable() })),
});
export const AvailabilitySchema = z.object({ date, rooms_left: count, from_total: MoneySchema.nullable() });
export const HotelDetailSchema = z.object({
  hotel: HotelSchema,
  card: z.object({ facts: z.array(z.object({ text: z.string(), source: SourceSchema })) }),
  tonight: FolioSchema.nullable(),
  availability: z.array(AvailabilitySchema),
});
export const AskRequestSchema = z.object({
  message: z.string().trim().min(1).max(600),
  history: z
    .array(z.object({ role: z.enum(["user", "assistant"]), content: z.string() }))
    .max(8)
    .optional(),
});
export const TraceSchema = z.object({
  step: count,
  tool: z.string(),
  args: z.record(z.string(), z.unknown()),
  started_ms: z.number().nonnegative(),
  duration_ms: z.number().nonnegative(),
  ok: z.boolean(),
  summary: z.string(),
  rate_ids: z.array(z.string()),
});
export const AnswerSchema = z.object({
  text: z.string(),
  prices: z.array(z.object({ amount: MoneySchema, rate_id: z.string().nullable(), traced: z.boolean() })),
  folios: z.array(FolioSchema),
  cited_cards: z.array(z.string()),
});
export const GroundingSchema = z.object({
  traced: count,
  total: count,
  ok: z.boolean(),
  cards_ok: z.boolean(),
  untraced: z.array(MoneySchema),
});
export const HoldRequestSchema = z.object({
  rate_id: z.string(),
  hold_token: z.string().min(32).max(4096),
  folio: FolioSchema,
});
export const HoldBodySchema = z.object({
  rate_id: z.string().min(1),
  hold_token: z.string().min(32).max(4096),
  confirm: z.literal(true),
});
export const HoldSchema = z.object({
  hold_id: z.string(),
  expires_at: time,
  folio: FolioSchema,
  mock: z.literal(true),
});
export const StreamErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  retry_after_s: z.number().nonnegative().optional(),
});
export const ErrorSchema = z.object({
  error: StreamErrorSchema,
  retry_after_s: z.number().nonnegative().optional(),
});
export const DoneSchema = z.object({
  mode: z.enum(["live", "replay"]),
  model: z.string().nullable(),
  steps: count,
  total_ms: z.number().nonnegative(),
});
export const EventSchemas = {
  trace: TraceSchema,
  answer: AnswerSchema,
  grounding: GroundingSchema,
  hold_request: HoldRequestSchema,
  error: StreamErrorSchema,
  done: DoneSchema,
};
export type AskEvent = {
  [K in keyof typeof EventSchemas]: { event: K; data: z.infer<(typeof EventSchemas)[K]> };
}[keyof typeof EventSchemas];
export const SampleSchema = z.object({
  id: z.string(),
  hotel_id: z.string(),
  hotel_name: z.string(),
  checkin: date,
  nights: count,
  feed: FolioSchema,
  landing: FolioSchema,
  match: z.boolean(),
  diff: z.array(
    z.object({ label: z.string(), feed: MoneySchema.nullable(), landing: MoneySchema.nullable() }),
  ),
  reason: z.string().nullable(),
  reason_label: z.string().nullable(),
  injected: z.string().nullable(),
  detected_reason: z.string().nullable(),
});
export const AccuracySchema = z.object({
  score: z.number().min(0).max(1),
  definition: z.string(),
  samples: z.array(SampleSchema),
  by_reason: z.record(z.string(), count),
  faults: z.array(z.string()),
});
export const FaultsSchema = z.array(
  z.object({
    id: z.string(),
    label: z.string(),
    description: z.string().optional(),
    google_reason: z.string(),
    sources: z.array(z.object({ label: z.string(), url: SourceSchema })),
  }),
);
export const FeedsSchema = z.object({
  items: z.array(
    z.object({
      kind: z.enum(["hotel_list", "property_data", "transaction", "ari_rate", "ari_avail", "ari_inv"]),
      filename: z.string(),
      bytes: count,
      schema_url: SourceSchema.nullable(),
      xsd_fetched_at: time.nullable(),
      valid: z.boolean(),
      check: z.enum(["xsd", "structural"]),
      errors: z.array(z.object({ line: count.nullable(), message: z.string() })),
    }),
  ),
});
export const TaxesSchema = z.object({
  rules: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      kind: z.enum(["percent", "per_room_night"]),
      value: z.string(),
      base: z.string(),
      applies_from: date,
      applies_to: date.nullable(),
      status: z.enum(["in_force", "suspended", "uncertain", "ended"]),
      source_url: SourceSchema,
      accessed: z.string(),
      confidence: ConfidenceSchema,
      note: z.string(),
    }),
  ),
  scenarios: z.array(z.object({ id: z.string(), label: z.string(), description: z.string() })),
});
// The contract intentionally leaves results.json open. Validate the run marker and
// JSON values, then display the actual tables without inventing metric names.
export const EvalSchema = z.object({ run_at: time.nullable() }).catchall(z.json());
export const FeedXmlSchema = z.string().refine((v) => v.trimStart().startsWith("<"), "Expected XML");
export const McpRequestSchema = z.object({
  jsonrpc: z.literal("2.0"),
  id: z.union([z.string(), z.number()]).optional(),
  method: z.string(),
  params: z.record(z.string(), z.json()).optional(),
});
export const McpResponseSchema = z.object({
  jsonrpc: z.literal("2.0"),
  id: z.union([z.string(), z.number()]).nullable(),
  result: z.json().optional(),
  error: z.object({ code: z.number(), message: z.string(), data: z.json().optional() }).optional(),
});
export type FolioData = z.infer<typeof FolioSchema>;
export type Hotel = z.infer<typeof HotelSchema>;
export type TraceData = z.infer<typeof TraceSchema>;
export type AnswerData = z.infer<typeof AnswerSchema>;
export type Sample = z.infer<typeof SampleSchema>;

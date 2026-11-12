import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";
import * as s from "./schema";
import { parseSSE, get, api, ApiError } from "./api";
import { formatMoney } from "./money";
import { parse, serialize } from "./filters";
const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const schemas: [string, z.ZodType][] = [
  ["meta", s.MetaSchema],
  ["hotels", s.HotelsSchema],
  ["hotel", s.HotelDetailSchema],
  ["quote", s.FolioSchema],
  ["accuracy", s.AccuracySchema],
  ["accuracy-faults", s.AccuracySchema],
  ["faults", s.FaultsSchema],
  ["feeds", s.FeedsSchema],
  ["taxes", s.TaxesSchema],
  ["eval", s.EvalSchema],
  ["eval-run", s.EvalSchema],
  ["holds", s.HoldSchema],
  ["ask-request", s.AskRequestSchema],
  ["hold-request", s.HoldBodySchema],
  ["error", s.ErrorSchema],
  ["mcp-request", s.McpRequestSchema],
  ["mcp", s.McpResponseSchema],
];
describe("published API contract", () => {
  it.each(schemas)("validates %s", (name, schema) =>
    expect(schema.safeParse(fixture(name)).success).toBe(true),
  );
  it("validates every stream event", () => {
    for (const e of fixture("ask"))
      expect(s.EventSchemas[e.event as keyof typeof s.EventSchemas].safeParse(e.data).success).toBe(true);
  });
  it("accepts the XML download shape", () =>
    expect(s.FeedXmlSchema.parse(readFileSync("tests/fixtures/feed.xml", "utf8"))).toContain("<listings>"));
  it("rejects non-decimal and numeric money", () => {
    for (const v of [1032.28, "1,032.28", "1032.2", "NaN"])
      expect(s.MoneySchema.safeParse(v).success).toBe(false);
  });
  it("requires explicit hold confirmation", () =>
    expect(s.HoldBodySchema.safeParse({ ...fixture("hold-request"), confirm: false }).success).toBe(false));
  it("requires the capability in both the hold event and POST body", () => {
    const body = fixture("hold-request");
    const event = fixture("ask").find((frame: { event: string }) => frame.event === "hold_request").data;
    for (const hold_token of [undefined, "", "short"]) {
      expect(s.HoldBodySchema.safeParse({ ...body, hold_token }).success).toBe(false);
      expect(s.HoldRequestSchema.safeParse({ ...event, hold_token }).success).toBe(false);
    }
  });
  it("returns the exact event capability when confirming a hold", async () => {
    const body = fixture("hold-request");
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(fixture("holds")));
    try {
      await api.hold(body.rate_id, body.hold_token);
      expect(fetch).toHaveBeenCalledWith(
        "/api/holds",
        expect.objectContaining({
          method: "POST",
        }),
      );
      expect(JSON.parse(fetch.mock.calls[0][1]!.body as string)).toEqual(body);
    } finally {
      fetch.mockRestore();
    }
  });
  it("rejects unsafe source protocols", () =>
    expect(s.SourceSchema.safeParse("javascript:alert(1)").success).toBe(false));
  it("checks ask bounds", () =>
    expect(s.AskRequestSchema.safeParse({ message: "x".repeat(601) }).success).toBe(false));
});
describe("money", () => {
  it.each([
    ["1032.28", "AED 1,032.28"],
    ["0.00", "AED 0.00"],
    ["-1234.50", "AED -1,234.50"],
    ["9999999999999999.99", "AED 9,999,999,999,999,999.99"],
  ])("formats %s without floating point", (value, result) => expect(formatMoney(value)).toBe(result));
});
describe("shareable filters", () => {
  it("round-trips recognised fields and ignores arbitrary parameters", () => {
    const f = parse(new URLSearchParams("q=metro&stars=3&area=Al+Jaddaf&unknown=yes"));
    expect(parse(new URLSearchParams(serialize(f)))).toEqual(f);
    expect(f).not.toHaveProperty("unknown");
  });
});
function stream(parts: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const p of parts) controller.enqueue(p);
      controller.close();
    },
  });
}
describe("POST SSE", () => {
  const raw = readFileSync("tests/fixtures/ask.sse", "utf8");
  it.each([1, 7, 97, 65536])("parses split UTF-8 chunks of %i bytes", async (size) => {
    const bytes = new TextEncoder().encode(raw);
    const chunks = [];
    for (let i = 0; i < bytes.length; i += size) chunks.push(bytes.slice(i, i + size));
    const result = [];
    for await (const event of parseSSE(stream(chunks))) result.push(event);
    expect(result).toEqual(fixture("ask"));
  });
  it("handles comments, CRLF, multiline JSON and final frame without delimiter", async () => {
    const input =
      ': heartbeat\r\nevent: done\r\ndata: {"mode":"replay",\r\ndata: "model":null,"steps":0,"total_ms":0}';
    const result = [];
    for await (const e of parseSSE(stream([new TextEncoder().encode(input)]))) result.push(e);
    expect(result[0].event).toBe("done");
  });
  it("fails visibly on malformed events", async () => {
    await expect(async () => {
      for await (const e of parseSSE(stream([new TextEncoder().encode("event: trace\ndata: {}\n\n")])))
        void e;
    }).rejects.toThrow();
  });
});
// fetch helpers are tested through browser routes in e2e; these exports must stay typed.
it("exposes a typed API error", () => {
  expect(new ApiError("wait", 429, 42).retryAfter).toBe(42);
  expect(get).toBeTypeOf("function");
});

import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { AnswerSchema, GroundingSchema, TraceSchema } from "./schema";
import { amountFromMention, assessGrounding } from "./grounding";
const events = JSON.parse(readFileSync("tests/fixtures/ask.json", "utf8")) as {
  event: string;
  data: unknown;
}[];
const answer = AnswerSchema.parse(events.find((e) => e.event === "answer")?.data);
const traces = events.filter((e) => e.event === "trace").map((e) => TraceSchema.parse(e.data));
it("requires card validity separately from price grounding", () => {
  const data = { traced: 1, total: 1, ok: true, cards_ok: false, untraced: [] };
  expect(GroundingSchema.parse(data)).toEqual(data);
  expect(GroundingSchema.safeParse({ ...data, cards_ok: undefined }).success).toBe(false);
  expect(GroundingSchema.safeParse({ ...data, cards_ok: "false" }).success).toBe(false);
});
it("requires a successful tool rate and matching folio amount", () => {
  expect(assessGrounding(answer, traces)).toEqual({ traced: 1, total: 2, ok: false });
  expect(assessGrounding(answer, [])).toEqual({ traced: 0, total: 2, ok: false });
});
it("flags a price hidden from the declared prices array", () => {
  const changed = { ...answer, prices: answer.prices.slice(0, 1) };
  expect(assessGrounding(changed, traces)).toEqual({ traced: 1, total: 2, ok: false });
});
it("rejects a forged amount paired with a real rate id", () => {
  const changed = {
    ...answer,
    text: "AED 900.00",
    prices: [{ amount: "900.00", traced: true, rate_id: answer.folios[0].rate_id }],
  };
  expect(assessGrounding(changed, traces).ok).toBe(false);
});
it("normalises mentions without converting money to a float", () => {
  expect(amountFromMention("AED 9,999,999,999,999,999.99")).toBe("9999999999999999.99");
  expect(amountFromMention("AED 20")).toBe("20.00");
});

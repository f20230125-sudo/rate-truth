import type { AnswerData, FolioData, TraceData } from "./schema";

export function amountFromMention(mention: string): string {
  const [whole, decimal = ""] = mention.replace(/AED\s*|,/gi, "").split(".");
  return `${whole.replace(/^0+(?=\d)/, "")}.${decimal.padEnd(2, "0")}`;
}
export const PRICE_PATTERN = /(AED\s*[\d,]+(?:\.\d{1,2})?)/gi;
export function tracedFolio(answer: AnswerData, traces: TraceData[], amount: string): FolioData | undefined {
  const reference = answer.prices.find(
    (p) =>
      p.amount === amount &&
      p.traced &&
      p.rate_id &&
      traces.some((t) => t.ok && t.rate_ids.includes(p.rate_id!)),
  );
  return reference
    ? answer.folios.find((f) => f.rate_id === reference.rate_id && f.total === amount)
    : undefined;
}
export function assessGrounding(answer: AnswerData, traces: TraceData[]) {
  const mentions = [...answer.text.matchAll(PRICE_PATTERN)].map((m) => amountFromMention(m[0]));
  const declared = answer.prices.map((p) => p.amount);
  const amounts = [...declared, ...new Set(mentions.filter((m) => !declared.includes(m)))];
  const traced = amounts.filter((amount) => tracedFolio(answer, traces, amount)).length;
  return { traced, total: amounts.length, ok: traced === amounts.length };
}

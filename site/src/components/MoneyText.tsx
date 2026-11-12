"use client";

import { PRICE_PATTERN, amountFromMention } from "@/lib/grounding";
import { Money } from "./Money";

export function MoneyText({ text, rateId, evidence }: { text: string; rateId?: string; evidence?: string }) {
  return text
    .split(PRICE_PATTERN)
    .map((part, i) =>
      /^AED\s*\d/i.test(part) ? (
        <Money
          key={i}
          amount={amountFromMention(part)}
          traced={!!(rateId || evidence)}
          rateId={rateId}
          evidence={evidence}
        />
      ) : (
        part
      ),
    );
}

"use client";

import { type AnswerData, type FolioData, type TraceData } from "@/lib/schema";
import { tracedFolio, PRICE_PATTERN, amountFromMention } from "@/lib/grounding";
import { FolioChip } from "./FolioChip";
import { Money } from "./Money";
import { Fragment, useId } from "react";
import { FolioUnfold } from "./FolioUnfold";

export function Answer({ answer, traces }: { answer: AnswerData; traces: TraceData[] }) {
  const seen = new Set<string>();
  const id = useId();
  const folios = new Map<string, FolioData>();
  const panelId = (folio: FolioData) => `${id}-${folio.rate_id}`;
  const price = (amount: string, key: string) => {
    seen.add(amount);
    const folio = tracedFolio(answer, traces, amount);
    if (!folio) return <Money key={key} amount={amount} traced={false} />;
    folios.set(folio.rate_id, folio);
    return <FolioChip key={key} folio={folio} panelId={panelId(folio)} />;
  };
  const parts = answer.text.split(PRICE_PATTERN);
  const text = parts.map((part, i) =>
    /^AED\s*[\d,]+/i.test(part) ? (
      price(amountFromMention(part), String(i))
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
  const extraPrices = answer.prices
    .filter((p) => !seen.has(p.amount))
    .map((p, i) => price(p.amount, `extra-${i}`));
  return (
    <div className="answer-text">
      <p className="answer-paragraph">
        {text}
        {extraPrices}
      </p>
      {Array.from(folios.values()).map((folio) => (
        <FolioUnfold key={folio.rate_id} folio={folio} id={panelId(folio)} />
      ))}
      {answer.cited_cards.length > 0 && (
        <p className="label">Content cards: {answer.cited_cards.join(", ")}</p>
      )}
    </div>
  );
}

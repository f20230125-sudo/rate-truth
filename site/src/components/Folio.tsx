"use client";

import { type FolioData } from "@/lib/schema";
import { MoneyText } from "./MoneyText";
import { Money } from "./Money";

export function Folio({ folio, different = [] }: { folio: FolioData; different?: string[] }) {
  return (
    <section className="folio" aria-label={`Folio for ${folio.hotel_name}`}>
      <div className="folio-title">
        <h3>{folio.hotel_name}</h3>
        <p>
          {folio.nights} {folio.nights === 1 ? "night" : "nights"} · {folio.checkin} · {folio.guests} guests
          <br />
          {folio.room} · {folio.refundable ? "Refundable" : "Non-refundable"} ·{" "}
          {folio.breakfast ? "Breakfast included" : "Room only"}
        </p>
      </div>
      <dl className="folio-lines">
        {folio.lines.map((line, i) => (
          <div
            className={`folio-line ${different.includes(line.label) ? "mismatch" : ""}`}
            key={`${line.rule_id}-${i}`}
          >
            <dt>
              {line.label}
              {line.basis && (
                <small>
                  <MoneyText text={line.basis} rateId={folio.rate_id} />
                </small>
              )}
            </dt>
            <dd className="line-amount">
              <Money amount={line.amount} traced rateId={folio.rate_id} />
            </dd>
            <dd className="rule-id">
              <span>{line.rule_id}</span>
              {line.source_url && (
                <span>
                  ·{" "}
                  <a href={line.source_url} target="_blank" rel="noopener noreferrer">
                    source ↗
                  </a>
                </span>
              )}
              {line.confidence && <span className="confidence">· {line.confidence}</span>}
            </dd>
          </div>
        ))}
      </dl>
      <div className="folio-total">
        <strong>All-in</strong>
        <Money amount={folio.total} traced rateId={folio.rate_id} />
      </div>
      <p className="folio-foot">
        <span>rate_id {folio.rate_id}</span>
        <br />
        Computed {folio.computed_at} · rules as of {folio.tax_rules_as_of}
        <br />
        Synthetic rate on a real hotel · {folio.hotel_id}
      </p>
    </section>
  );
}

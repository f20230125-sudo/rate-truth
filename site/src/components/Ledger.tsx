"use client";

import { type ReactNode } from "react";

export function Ledger({ facts }: { facts: { label: string; value: ReactNode; source?: string }[] }) {
  return (
    <dl className="ledger">
      {facts.map((fact, i) => (
        <div key={i}>
          <dt>{fact.label}</dt>
          <dd>
            {fact.value}
            {fact.source && (
              <>
                {" "}
                <a href={fact.source} target="_blank" rel="noopener noreferrer">
                  source ↗
                </a>
              </>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

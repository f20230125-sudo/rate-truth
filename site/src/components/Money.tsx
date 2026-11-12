"use client";

import { formatMoney } from "@/lib/money";

export function Money({
  amount,
  traced,
  rateId,
  evidence,
}: {
  amount: string;
  traced: boolean;
  rateId?: string | null;
  evidence?: string;
}) {
  const valid = traced && !!(rateId || evidence);
  return (
    <span className={valid ? "money" : "money alarm untraced"}>
      {valid ? (
        formatMoney(amount)
      ) : (
        <>
          <s>{formatMoney(amount)}</s>
          <span className="untraced-note">not traced to a tool result</span>
        </>
      )}
    </span>
  );
}

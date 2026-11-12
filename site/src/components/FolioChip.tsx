"use client";

import { type FolioData } from "@/lib/schema";
import { useQuery } from "@/lib/hooks";
import { setUrl } from "@/lib/filters";
import { Money } from "./Money";
import { useId } from "react";
import { FolioUnfold } from "./FolioUnfold";

export function FolioChip({
  folio,
  label,
  panelId,
  queryKey = "folio",
}: {
  folio: FolioData;
  label?: string;
  panelId?: string;
  queryKey?: string;
}) {
  const generatedId = useId();
  const query = useQuery();
  const open = new URLSearchParams(query).get(queryKey) === folio.rate_id;
  const controls = panelId ?? generatedId;
  const chip = (
    <button
      className="folio-chip"
      aria-expanded={open}
      aria-controls={controls}
      onClick={() => setUrl(queryKey, open ? null : folio.rate_id)}
    >
      {label && `${label} `}
      <Money amount={folio.total} traced rateId={folio.rate_id} />
      <span aria-hidden="true"> {open ? "−" : "+"}</span>
    </button>
  );
  if (panelId) return chip;
  return (
    <div className="chip-wrap">
      {chip}
      <FolioUnfold folio={folio} id={controls} queryKey={queryKey} />
    </div>
  );
}

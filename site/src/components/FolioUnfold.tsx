"use client";

import { useQuery } from "@/lib/hooks";
import { type FolioData } from "@/lib/schema";
import { Folio } from "./Folio";

export function FolioUnfold({
  folio,
  id,
  queryKey = "folio",
}: {
  folio: FolioData;
  id: string;
  queryKey?: string;
}) {
  const query = useQuery();
  const open = new URLSearchParams(query).get(queryKey) === folio.rate_id;
  return (
    <div className="unfold" id={id} hidden={!open}>
      {open && <Folio folio={folio} />}
    </div>
  );
}

"use client";

import { useQuery, useData } from "@/lib/hooks";
import { parse, serialize } from "@/lib/filters";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { Loading } from "./Loading";
import { HotelFilters } from "./HotelFilters";
import { HotelRow } from "./HotelRow";

export function Hotels() {
  const query = useQuery();
  const params = new URLSearchParams(query);
  const filters = parse(params);
  const qs = serialize(filters);
  const open = params.get("hotel");
  const load = useCallback((signal: AbortSignal) => api.hotels(qs, signal), [qs]);
  const { data, error } = useData(load);
  return (
    <>
      <HotelFilters filters={filters} />
      {!data ? (
        <Loading error={error} />
      ) : (
        <>
          <p className="label">{data.total} HOTELS / OPEN A ROW TO READ THE EVIDENCE</p>
          <div className="hotel-list">
            {data.items.map((h) => (
              <HotelRow key={h.id} hotel={h} open={open} />
            ))}
          </div>
          {data.items.length === 0 && <p>No hotels match those filters. Clear a filter to try again.</p>}
        </>
      )}
      <p className="keys-hint">
        Keyboard: <kbd>/</kbd> search · <kbd>j</kbd> / <kbd>k</kbd> move · <kbd>Enter</kbd> open ·{" "}
        <kbd>Esc</kbd> close
      </p>
    </>
  );
}

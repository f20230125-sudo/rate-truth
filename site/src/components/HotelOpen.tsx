"use client";

import { useCallback } from "react";
import { api } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { Loading } from "./Loading";
import { Ledger } from "./Ledger";
import { Folio } from "./Folio";
import { Strip } from "./Strip";
import { summaryFacts } from "@/lib/hotel-facts";

export function HotelOpen({ id }: { id: string }) {
  const load = useCallback((signal: AbortSignal) => api.hotel(id, signal), [id]);
  const { data, error } = useData(load);
  if (!data) return <Loading error={error} />;
  const ledgerFacts = (facts: typeof data.card.facts) =>
    facts.map((f) => ({ label: "OSM fact", value: f.text, source: f.source }));
  return (
    <div className="hotel-open unfold">
      <h3>Content card · facts with their sources</h3>
      <Ledger facts={ledgerFacts(summaryFacts(data.hotel, data.card.facts))} />
      <details>
        <summary>Show all {data.card.facts.length} facts</summary>
        <Ledger facts={ledgerFacts(data.card.facts)} />
      </details>
      <details>
        <summary>OSM elements ({data.hotel.mapped_osm_ids.length})</summary>
        <ul>
          {data.hotel.mapped_osm_ids.map((osmId) => (
            <li key={osmId}>
              <a href={`https://www.openstreetmap.org/${osmId}`} target="_blank" rel="noopener noreferrer">
                {osmId}
              </a>
            </li>
          ))}
        </ul>
      </details>
      <div className="section-heading">
        <h3>Tonight’s folio</h3>
        <span className="label">SYNTHETIC RATE</span>
      </div>
      {data.tonight ? <Folio folio={data.tonight} /> : <p>No rate available for tonight.</p>}
      <h3>Next 30 nights</h3>
      <Strip
        items={data.availability.map((n) => ({
          id: n.date,
          label: `${n.date}: ${n.rooms_left} rooms left`,
          ok: n.rooms_left > 0,
        }))}
      />
      <p className="small muted">Each mark is one night. × means no rooms left. Availability is synthetic.</p>
    </div>
  );
}

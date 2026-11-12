"use client";
import { setUrl } from "@/lib/filters";
import { formatDistance } from "@/lib/distance";
import type { Hotel, FolioData } from "@/lib/schema";
import { FolioChip } from "./FolioChip";
import { HotelOpen } from "./HotelOpen";

export function HotelRow({
  hotel: h,
  open,
}: {
  hotel: Hotel & { from_folio: FolioData | null };
  open: string | null;
}) {
  const isOpen = h.mapped_osm_ids.includes(open ?? "");
  const english = h.name_en && /[^\p{Script=Latin}\p{N}\p{P}\p{Z}\p{S}]/u.test(h.name) ? h.name_en : null;
  return (
    <article className="hotel-row">
      <button
        data-row
        className="row-head"
        aria-expanded={isOpen}
        onClick={() => setUrl("hotel", isOpen ? null : h.id)}
      >
        <span>
          <span className="hotel-name">
            {h.name}
            {english && <> · {english}</>}
          </span>
          {h.mapped_osm_ids.length > 1 && (
            <span className="small muted">also mapped as {h.mapped_osm_ids.length} OSM elements</span>
          )}
          <span className="small muted">
            {h.area ?? "Area not tagged"} ·{" "}
            {h.stars !== null
              ? `${h.stars} stars · OSM tag`
              : h.stars_estimated !== null
                ? `${h.stars_estimated} stars · estimated`
                : "Stars not tagged"}
          </span>
        </span>
        <span className="small">
          Metro {h.nearest_metro ? formatDistance(h.nearest_metro.metres) : "unknown"}
          <br />
          Beach {h.nearest_beach ? formatDistance(h.nearest_beach.metres) : "unknown"}
        </span>
        <span aria-hidden="true">{isOpen ? "−" : "+"}</span>
      </button>
      {h.from_folio ? (
        <FolioChip folio={h.from_folio} label="From · all-in tonight" />
      ) : (
        <p className="muted small">No rate for tonight.</p>
      )}
      {isOpen && <HotelOpen id={open!} />}
    </article>
  );
}

"use client";
import { setUrl, type Filters } from "@/lib/filters";

export function HotelFilters({ filters }: { filters: Filters }) {
  return (
    <form className="filters" onSubmit={(e) => e.preventDefault()}>
      <label>
        Search hotels
        <input
          data-search
          type="search"
          value={filters.q ?? ""}
          onChange={(e) => setUrl("q", e.target.value)}
        />
      </label>
      <label>
        Area
        <input
          value={filters.area ?? ""}
          onChange={(e) => setUrl("area", e.target.value)}
          placeholder="Any area"
        />
      </label>
      <label>
        Stars
        <select value={filters.stars ?? ""} onChange={(e) => setUrl("stars", e.target.value)}>
          <option value="">Any</option>
          {[1, 2, 3, 4, 5].map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={filters.near_metro === "true"}
          onChange={(e) => setUrl("near_metro", e.target.checked ? "true" : null)}
        />
        Near metro
      </label>
    </form>
  );
}

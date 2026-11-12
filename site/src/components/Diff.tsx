"use client";

import { type Sample } from "@/lib/schema";
import { Folio } from "./Folio";

export function Diff({ sample }: { sample: Sample }) {
  const labels = sample.diff.map((d) => d.label);
  return (
    <section className="diff">
      <div className="section-heading">
        <h2>Feed against landing page</h2>
        <span className={sample.match ? "muted" : "alarm"}>
          {sample.match
            ? "✓ Match"
            : `${sample.reason_label ?? "Mismatch"} · ${sample.reason ?? "unclassified"}`}
        </span>
      </div>
      {sample.injected && (
        <p className="alarm">
          Injected: {sample.injected} · detected: {sample.detected_reason ?? "not detected"}
        </p>
      )}
      <div className="diff-grid">
        <div>
          <h3 className="label">FEED FOLIO</h3>
          <Folio folio={sample.feed} different={labels} />
        </div>
        <div>
          <h3 className="label">LANDING FOLIO</h3>
          <Folio folio={sample.landing} different={labels} />
        </div>
      </div>
    </section>
  );
}

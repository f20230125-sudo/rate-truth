"use client";

import { type TraceData } from "@/lib/schema";
import { MoneyText } from "./MoneyText";

export function Trace({ rows, openRate }: { rows: TraceData[]; openRate: (id: string) => void }) {
  return (
    <details className="trace" open>
      <summary>
        Tool trace <span className="label">{rows.length} returned</span>
      </summary>
      <div className="trace-head label">
        <span>elapsed</span>
        <span>tool / arguments / result</span>
      </div>
      {rows.length ? (
        <ol>
          {rows.map((row) => (
            <li key={row.step} className={row.ok ? "" : "alarm"}>
              <span className="trace-time">
                {row.started_ms} ms
                <br />
                <span>+{row.duration_ms}</span>
              </span>
              <div>
                <strong className="mono">{row.tool}</strong>
                <code>{JSON.stringify(row.args)}</code>
                <p>
                  {row.ok ? "✓ " : "× "}
                  <MoneyText text={row.summary} rateId={row.ok ? row.rate_ids[0] : undefined} />
                </p>
                {row.rate_ids.map((id) => (
                  <button key={id} className="text-button mono" onClick={() => openRate(id)}>
                    rate_id {id} ↗
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="muted">Tool calls appear here as they return.</p>
      )}
    </details>
  );
}

"use client";

import { useId, useState } from "react";
import { type Sample } from "@/lib/schema";
import { SampleRow } from "./SampleRow";

export function SampleLedger({ samples, selected }: { samples: Sample[]; selected?: string }) {
  const [expanded, setExpanded] = useState(false);
  const matchesId = useId();
  const indexed = samples.map((sample, index) => ({ sample, index }));
  const mismatches = indexed.filter(({ sample }) => !sample.match);
  const matches = indexed.filter(({ sample }) => sample.match);

  return (
    <section aria-label="Sample ledger">
      <h2>Sample ledger</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Sample / hotel</th>
              <th>Stay</th>
              <th>Result</th>
              <th>Reason code</th>
            </tr>
          </thead>
          <tbody>
            {mismatches.map(({ sample, index }) => (
              <SampleRow key={sample.id} sample={sample} index={index} selected={selected} />
            ))}
            {matches.length > 0 && (
              <tr>
                <td colSpan={4}>
                  <button
                    className="text-button"
                    aria-expanded={expanded}
                    aria-controls={matchesId}
                    onClick={() => setExpanded(!expanded)}
                  >
                    {matches.length}
                    {mismatches.length > 0 ? " more" : ""} samples matched — {expanded ? "hide" : "show"}
                  </button>
                </td>
              </tr>
            )}
          </tbody>
          <tbody id={matchesId} hidden={!expanded}>
            {expanded &&
              matches.map(({ sample, index }) => (
                <SampleRow key={sample.id} sample={sample} index={index} selected={selected} />
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

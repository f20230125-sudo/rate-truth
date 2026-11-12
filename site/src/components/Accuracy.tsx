"use client";

import { useQuery, useData } from "@/lib/hooks";
import { FaultBench } from "./FaultBench";
import { SampleLedger } from "./SampleLedger";
import { useCallback } from "react";
import { api } from "@/lib/api";
import { Score } from "./Score";
import { MoneyText } from "./MoneyText";
import { Strip } from "./Strip";
import { setUrl } from "@/lib/filters";
import { Loading } from "./Loading";
import { Diff } from "./Diff";
import { dubaiToday } from "@/lib/dates";

export function Accuracy() {
  const query = useQuery();
  const params = new URLSearchParams(query);
  const faults = params.get("faults") ?? "";
  const selected = params.get("sample");
  const loader = useCallback(
    (signal: AbortSignal) => api.accuracy(`faults=${encodeURIComponent(faults)}`, signal),
    [faults],
  );
  const { data, error } = useData(loader);
  const sample =
    data?.samples.find((s) => s.id === selected) ??
    data?.samples.find((s) => s.checkin > dubaiToday()) ??
    data?.samples[0];
  return (
    <>
      {data ? (
        <>
          <div className="score-block">
            <Score value={data.score} />
            <div>
              <h2>Price accuracy</h2>
              <p>
                {data.samples.filter((s) => s.match).length} of {data.samples.length} sampled stays match.
              </p>
              <details>
                <summary>How this score is defined</summary>
                <p>
                  <MoneyText text={data.definition} evidence="accuracy definition threshold" />
                </p>
                <p className="small muted">
                  Our metric, inspired by Google’s published description. This is a local audit, not a Google
                  score.
                </p>
              </details>
            </div>
          </div>
          <Strip
            items={data.samples.map((s, i) => ({
              id: s.id,
              label: `Sample ${i + 1}: ${s.match ? "match" : "mismatch"}`,
              ok: s.match,
            }))}
            selected={sample?.id}
            onSelect={(id) => setUrl("sample", id)}
          />
        </>
      ) : (
        <Loading error={error} />
      )}
      <FaultBench faults={faults} />
      {data && (
        <>
          <SampleLedger samples={data.samples} selected={sample?.id} />
          {sample && <Diff sample={sample} />}
        </>
      )}
    </>
  );
}

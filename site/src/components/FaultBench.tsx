"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { setUrl } from "@/lib/filters";
import { useData } from "@/lib/hooks";
import { Loading } from "./Loading";

export function FaultBench({ faults }: { faults: string }) {
  const [chosen, setChosen] = useState<string[]>(faults.split(",").filter(Boolean));
  const faultList = useData(api.faults);
  return (
    <section className="fault-bench">
      <div className="section-heading">
        <h2>Fault bench</h2>
        <span className="label">PER REQUEST / NEVER STORED</span>
      </div>
      <p>Inject a fault into this audit. The classifier should name the cause.</p>
      {faultList.data ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setUrl("faults", chosen.join(","));
          }}
        >
          {faultList.data.map((f) => (
            <div className="fault-option" key={f.id}>
              <input
                id={`fault-${f.id}`}
                type="checkbox"
                checked={chosen.includes(f.id)}
                onChange={(e) =>
                  setChosen((old) => (e.target.checked ? [...old, f.id] : old.filter((id) => id !== f.id)))
                }
              />
              <span>
                <label htmlFor={`fault-${f.id}`}>{f.label}</label>
                {f.description && <small>{f.description}</small>}
                {f.sources.map((source) => (
                  <small key={source.url}>
                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                      {source.label}
                    </a>
                  </small>
                ))}
              </span>
            </div>
          ))}
          <div className="actions">
            <button className="button primary">Run audit</button>
            <button
              type="button"
              className="button"
              onClick={() => {
                setChosen([]);
                setUrl("faults", null);
              }}
            >
              Reset faults
            </button>
          </div>
        </form>
      ) : (
        <Loading error={faultList.error} />
      )}
    </section>
  );
}

"use client";

import { useData, errorMessage } from "@/lib/hooks";
import { api } from "@/lib/api";
import { useState } from "react";
import { type FolioData } from "@/lib/schema";
import { Loading } from "./Loading";
import { Ledger } from "./Ledger";
import { Money } from "./Money";
import { Folio } from "./Folio";

export function Taxes() {
  const { data, error } = useData(api.taxes);
  const [folio, setFolio] = useState<FolioData>();
  const [quoteError, setQuoteError] = useState("");
  const [busy, setBusy] = useState("");
  if (!data) return <Loading error={error} />;
  async function quote(id: string, asOf: string) {
    setBusy(id);
    setQuoteError("");
    try {
      const hotels = await api.hotels("limit=1");
      if (!hotels.items[0]) throw new Error("No hotel is available to price this stay.");
      const checkin = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Dubai" });
      setFolio(
        await api.quote(
          new URLSearchParams({
            hotel_id: hotels.items[0].id,
            checkin,
            nights: "2",
            guests: "2",
            plan: "refundable",
            as_of: asOf,
          }).toString(),
        ),
      );
    } catch (e) {
      setQuoteError(errorMessage(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <div className="timeline">
        {data.rules.map((r) => (
          <section className="tax-row" key={r.id}>
            <div className="tax-date mono small">
              {r.applies_from}
              <br />
              {r.applies_to ? `to ${r.applies_to}` : "onwards"}
            </div>
            <div>
              <div className="section-heading">
                <h2>{r.label}</h2>
                <span className={r.status === "uncertain" ? "alarm" : ""}>
                  {r.status.replaceAll("_", " ")}
                </span>
              </div>
              <Ledger
                facts={[
                  { label: "Rule", value: <span className="mono small">{r.id}</span> },
                  {
                    label: "Basis",
                    value:
                      r.kind === "percent" ? (
                        `${r.value}% · ${r.base}`
                      ) : (
                        <>
                          <Money amount={Number(r.value).toFixed(2)} traced evidence={r.id} /> per room-night
                          · {r.base}
                        </>
                      ),
                  },
                  { label: "Confidence", value: r.confidence },
                  {
                    label: "Evidence",
                    value: (
                      <>
                        <a href={r.source_url}>Source ↗</a> · accessed {r.accessed}
                      </>
                    ),
                  },
                ]}
              />
              <p>{r.note}</p>
              <button
                className="text-button"
                disabled={!!busy}
                onClick={() => void quote(r.id, r.applies_from)}
              >
                {busy === r.id ? "Pricing…" : "Price a two-night stay under this rule ↗"}
              </button>
            </div>
          </section>
        ))}
      </div>
      {data.scenarios.length > 0 && (
        <section>
          <h2>Effective-date scenarios</h2>
          {data.scenarios.map((s) => (
            <p key={s.id}>
              <strong>{s.label}</strong> · {s.description}
            </p>
          ))}
        </section>
      )}
      {quoteError && <Loading error={quoteError} />}
      {folio && <Folio folio={folio} />}
    </>
  );
}

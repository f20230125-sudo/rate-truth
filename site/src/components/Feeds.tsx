"use client";

import { useData, errorMessage } from "@/lib/hooks";
import { api } from "@/lib/api";
import { useState } from "react";
import { Loading } from "./Loading";
import { Ledger } from "./Ledger";

export function Feeds() {
  const { data, error } = useData(api.feeds);
  const [downloadError, setDownloadError] = useState("");
  async function download(filename: string) {
    setDownloadError("");
    try {
      const xml = await api.feed(filename);
      const url = URL.createObjectURL(new Blob([xml], { type: "application/xml" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setDownloadError(errorMessage(e));
    }
  }
  if (!data) return <Loading error={error} />;
  return (
    <div className="feed-list">
      {downloadError && <Loading error={downloadError} />}
      {data.items.map((f) => (
        <section className="feed-row" key={f.kind}>
          <div className="section-heading">
            <h2>{f.kind.replaceAll("_", " ")}</h2>
            <span className={f.valid ? "" : "alarm"}>
              {f.valid ? "✓" : "×"}{" "}
              {f.check === "structural"
                ? `Structurally ${f.valid ? "checked" : "failed"}`
                : `XSD ${f.valid ? "valid" : "invalid"}`}
            </span>
          </div>
          <Ledger
            facts={[
              { label: "File", value: f.filename },
              { label: "Size", value: `${f.bytes.toLocaleString()} bytes` },
              {
                label: "Schema",
                value: f.schema_url ? (
                  <a href={f.schema_url}>Published schema ↗</a>
                ) : (
                  "No published XSD; structural checks only"
                ),
              },
              { label: "XSD fetched", value: f.xsd_fetched_at ?? "Not applicable" },
            ]}
          />
          {f.errors.length > 0 && (
            <ul className="alarm">
              {f.errors.map((e, i) => (
                <li key={i}>
                  Line {e.line ?? "unknown"}: {e.message}
                </li>
              ))}
            </ul>
          )}
          <a
            className="download"
            href={`/api/feeds/${encodeURIComponent(f.filename)}`}
            download
            onClick={(e) => {
              e.preventDefault();
              void download(f.filename);
            }}
          >
            Download {f.filename} ↓
          </a>
        </section>
      ))}
    </div>
  );
}

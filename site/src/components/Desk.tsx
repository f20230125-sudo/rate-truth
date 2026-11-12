"use client";

import { useData, errorMessage } from "@/lib/hooks";
import { api, ask, ApiError } from "@/lib/api";
import { useState, useRef, useEffect } from "react";
import { type TraceData, type AnswerData, type AskEvent } from "@/lib/schema";
import { assessGrounding } from "@/lib/grounding";
import { Loading } from "./Loading";
import { DeskRequest } from "./DeskRequest";
import { Answer } from "./Answer";
import { ConfirmHold } from "./ConfirmHold";
import { Trace } from "./Trace";
import { setUrl } from "@/lib/filters";

export function Desk() {
  const meta = useData(api.meta);
  const [message, setMessage] = useState("");
  const [rows, setRows] = useState<TraceData[]>([]);
  const [answer, setAnswer] = useState<AnswerData>();
  const [grounding, setGrounding] = useState<Extract<AskEvent, { event: "grounding" }>["data"]>();
  const [hold, setHold] = useState<Extract<AskEvent, { event: "hold_request" }>["data"]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<string>();
  const currentMode = mode ?? meta.data?.llm_mode;
  const [history, setHistory] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  async function run(text: string) {
    if (!text.trim() || busy) return;
    abort.current?.abort();
    abort.current = new AbortController();
    setMessage(text);
    setBusy(true);
    setRows([]);
    setAnswer(undefined);
    setGrounding(undefined);
    setHold(undefined);
    setError("");
    let answerText = "";
    try {
      await ask(
        { message: text, history: history.slice(-8) },
        (event) => {
          switch (event.event) {
            case "trace":
              setRows((current) => [...current, event.data]);
              break;
            case "answer":
              setAnswer(event.data);
              answerText = event.data.text;
              break;
            case "grounding":
              setGrounding(event.data);
              break;
            case "hold_request":
              setHold(event.data);
              break;
            case "done":
              setMode(event.data.mode);
              break;
            case "error":
              if (event.data.code === "live_model_busy") {
                setError(
                  `${event.data.message}${event.data.retry_after_s !== undefined ? ` Retry in ${event.data.retry_after_s} seconds.` : ""}`,
                );
                break;
              }
              setError(
                errorMessage(
                  new ApiError(
                    event.data.message,
                    event.data.retry_after_s !== undefined ? 429 : 500,
                    event.data.retry_after_s,
                  ),
                ),
              );
              break;
          }
        },
        abort.current.signal,
      );
      setHistory((current) =>
        [
          ...current,
          { role: "user" as const, content: text },
          ...(answerText ? [{ role: "assistant" as const, content: answerText }] : []),
        ].slice(-8),
      );
    } catch (e) {
      if (!abort.current.signal.aborted) setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  const assessed = answer ? assessGrounding(answer, rows) : { traced: 0, total: 0, ok: false };
  const actualTraced = assessed.traced;
  const fullyGrounded =
    grounding?.ok &&
    grounding.total === assessed.total &&
    grounding.traced === assessed.traced &&
    assessed.ok;
  return (
    <>
      <div className="desk-meta">
        <span className="label">MCP SUPPLIER DESK</span>
        <span className="label">
          {currentMode === "replay"
            ? "OFFLINE REPLAY · no live language model"
            : currentMode === "live"
              ? "LIVE · bounded agent loop"
              : "Checking agent mode…"}
        </span>
      </div>
      {meta.error && <Loading error={meta.error} />}
      <div className="desk-grid">
        <section className="desk-main">
          <h1>
            Every price has <br />a paper trail.
          </h1>
          <p className="lede">Ask for a stay in Dubai. Follow the tools, unfold the bill, check the total.</p>
          <DeskRequest message={message} busy={busy} onAsk={run} onMessageChange={setMessage} />
          {error && (
            <p role="alert" className="notice alarm">
              {error}
            </p>
          )}
          {answer && (
            <section className="answer" aria-label="Desk answer">
              <h2>The desk’s answer</h2>
              <Answer answer={answer} traces={rows} />
              {assessed.total === 0 ? (
                <p className="small muted">No prices in this answer.</p>
              ) : (
                grounding && (
                  <div className={`grounding ${fullyGrounded ? "" : "alarm"}`} role="status">
                    {fullyGrounded ? "✓" : "×"} {actualTraced} of {assessed.total} prices traced to rate_id{" "}
                    {answer.prices
                      .filter((p) => p.traced && p.rate_id)
                      .map((p) => p.rate_id)
                      .join(", ") || "none"}
                    .{!fullyGrounded && " Grounded check failed."}
                  </div>
                )
              )}
            </section>
          )}
          {hold && (
            <ConfirmHold
              key={hold.hold_token}
              hold={hold.folio}
              holdToken={hold.hold_token}
              busy={busy}
              setError={setError}
            />
          )}
        </section>
        <aside className="desk-trace" aria-label="Supplier tool trace">
          <Trace rows={rows} openRate={(id) => setUrl("folio", id)} />
        </aside>
      </div>
      <p className="desk-note">
        Synthetic rates on real hotels. Every amount comes from the supplier engine.
        <br />
        Holds are mock-only. No booking or payment takes place.
      </p>
    </>
  );
}

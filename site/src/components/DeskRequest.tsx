"use client";

export function DeskRequest({
  message,
  busy,
  onAsk,
  onMessageChange,
}: {
  message: string;
  busy: boolean;
  onAsk: (message: string) => Promise<void>;
  onMessageChange: (message: string) => void;
}) {
  return (
    <>
      {" "}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void onAsk(message);
        }}
      >
        <label className="label" htmlFor="ask">
          YOUR STAY REQUEST
        </label>
        <textarea
          data-search
          id="ask"
          maxLength={600}
          value={message}
          onChange={(e) => onMessageChange(e.target.value)}
          placeholder="Two nights near a metro, refundable, for two guests…"
          required
        />
        <div className="form-tail">
          <span className="muted small">
            {message.length}/600 · <kbd>/</kbd> to focus
          </span>
          <button className="button primary" disabled={busy}>
            {busy ? "Following the tools…" : "Ask the desk ↗"}
          </button>
        </div>
      </form>
      <div className="suggestions">
        <span className="label">TRY A REQUEST</span>
        {[
          "Find a refundable stay near a metro for two nights.",
          "Compare two hotels and explain every fee.",
          "Find a stay and prepare a mock hold.",
        ].map((text) => (
          <button key={text} className="text-button" disabled={busy} onClick={() => void onAsk(text)}>
            {text} ↗
          </button>
        ))}
      </div>
    </>
  );
}

"use client";

import { useState } from "react";

export function CopyBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <div className="copy-block">
      <pre>
        <code>{text}</code>
      </pre>
      <button
        className="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
          } catch {
            setFailed(true);
          }
        }}
      >
        {copied ? "Copied" : `Copy ${label}`}
      </button>
      {failed && <p role="status">Clipboard unavailable. Select and copy the text above.</p>}
    </div>
  );
}

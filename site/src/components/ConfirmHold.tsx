"use client";

import { useId, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import { type FolioData } from "@/lib/schema";
import { checkoutDate } from "@/lib/dates";
import { FolioChip } from "./FolioChip";
import { FolioUnfold } from "./FolioUnfold";

export function ConfirmHold({
  hold,
  holdToken,
  busy,
  setError,
}: {
  hold: FolioData;
  holdToken: string;
  busy: boolean;
  setError: (message: string) => void;
}) {
  const panelId = useId();
  const [held, setHeld] = useState<Awaited<ReturnType<typeof api.hold>>>();
  const [holding, setHolding] = useState(false);
  // A hold unfolds independently of the same rate cited in the answer.
  return (
    <section className="hold">
      <h2>Confirm a mock hold</h2>
      <p>
        This request has not placed a hold. Confirm to create a temporary mock hold; it never books a room.
      </p>
      <p className="hold-summary">
        {hold.hotel_name} · {hold.checkin} – {checkoutDate(hold.checkin, hold.nights)} · all-in{" "}
        <FolioChip folio={hold} panelId={panelId} queryKey="hold_folio" /> ·{" "}
        <span className="mono small">rate_id {hold.rate_id}</span>
      </p>
      <FolioUnfold folio={hold} id={panelId} queryKey="hold_folio" />
      {held ? (
        <p role="status">
          Mock hold {held.hold_id} · expires {held.expires_at}
        </p>
      ) : (
        <button
          className="button primary"
          disabled={holding || busy}
          onClick={async () => {
            setHolding(true);
            try {
              setHeld(await api.hold(hold.rate_id, holdToken));
            } catch (e) {
              setError(errorMessage(e));
            } finally {
              setHolding(false);
            }
          }}
        >
          {holding ? "Creating mock hold…" : "Confirm mock hold"}
        </button>
      )}
    </section>
  );
}

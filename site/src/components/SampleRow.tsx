"use client";

import { setUrl } from "@/lib/filters";
import { type Sample } from "@/lib/schema";

export function SampleRow({ sample, index, selected }: { sample: Sample; index: number; selected?: string }) {
  return (
    <tr data-selected={selected === sample.id}>
      <td>
        <button data-row className="text-button" onClick={() => setUrl("sample", sample.id)}>
          {String(index + 1).padStart(2, "0")} · {sample.hotel_name}
        </button>
      </td>
      <td>
        {sample.checkin} · {sample.nights}n
      </td>
      <td className={sample.match ? "" : "alarm"}>{sample.match ? "✓ Match" : "× Mismatch"}</td>
      <td className="mono small">{sample.reason ?? "—"}</td>
    </tr>
  );
}

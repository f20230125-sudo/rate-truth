"use client";

import { useEffect } from "react";
import { setUrl } from "@/lib/filters";

export function Keyboard() {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable;
      if (event.key === "Escape") {
        document.querySelectorAll<HTMLDetailsElement>("details[open]").forEach((d) => (d.open = false));
        for (const key of ["hotel", "folio", "hold_folio"]) {
          if (new URLSearchParams(location.search).has(key)) setUrl(key, null);
        }
        if (typing) target.blur();
        return;
      }
      if (typing || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "/") {
        event.preventDefault();
        document.querySelector<HTMLElement>("[data-search]")?.focus();
      }
      if (event.key === "j" || event.key === "k") {
        const rows = [...document.querySelectorAll<HTMLElement>("[data-row]")];
        const at = rows.indexOf(document.activeElement as HTMLElement);
        const index = event.key === "j" ? Math.min(rows.length - 1, at + 1) : Math.max(0, at - 1);
        rows[index]?.focus();
        rows[index]?.scrollIntoView({ block: "nearest" });
        event.preventDefault();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  return null;
}

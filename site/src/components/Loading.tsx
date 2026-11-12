"use client";

export function Loading({ error }: { error?: string }) {
  return error ? (
    <p className="notice alarm" role="alert">
      {error}
    </p>
  ) : (
    <p className="muted" role="status">
      Reading the supplier API…
    </p>
  );
}

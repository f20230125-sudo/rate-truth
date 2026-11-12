"use client";

export function Strip({
  items,
  selected,
  onSelect,
}: {
  items: { id: string; label: string; ok: boolean }[];
  selected?: string;
  onSelect?: (id: string) => void;
}) {
  return (
    <div className="strip" aria-label="Sample strip">
      {items.map((item) =>
        onSelect ? (
          <button
            key={item.id}
            className={item.ok ? "match" : "mismatch"}
            aria-label={item.label}
            aria-pressed={selected === item.id}
            title={item.label}
            onClick={() => onSelect(item.id)}
          >
            {item.ok ? "✓" : "×"}
          </button>
        ) : (
          <span
            key={item.id}
            className={item.ok ? "match" : "mismatch"}
            title={item.label}
            aria-label={item.label}
          >
            {item.ok ? "│" : "×"}
          </span>
        ),
      )}
    </div>
  );
}

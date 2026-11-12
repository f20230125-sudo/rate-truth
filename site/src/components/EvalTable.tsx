"use client";

export function EvalTable({ name, value }: { name: string; value: unknown }) {
  if (value === null) return <p>{name}: not reported</p>;
  if (typeof value !== "object")
    return (
      <p>
        {name}: <span className="mono">{String(value)}</span>
      </p>
    );
  if (Array.isArray(value))
    return (
      <section>
        <h3>{name.replaceAll("_", " ")}</h3>
        {value.map((row, i) => (
          <EvalTable key={i} name={`Row ${i + 1}`} value={row} />
        ))}
      </section>
    );
  const entries = Object.entries(value);
  const flat = entries.filter(([, v]) => v === null || typeof v !== "object");
  return (
    <section>
      <h3>{name.replaceAll("_", " ")}</h3>
      {flat.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Reported value</th>
              </tr>
            </thead>
            <tbody>
              {flat.map(([key, v]) => (
                <tr key={key}>
                  <th>{key.replaceAll("_", " ")}</th>
                  <td className="mono">{v === null ? "not reported" : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {entries
        .filter(([, v]) => v !== null && typeof v === "object")
        .map(([key, v]) => (
          <EvalTable key={key} name={key} value={v} />
        ))}
    </section>
  );
}

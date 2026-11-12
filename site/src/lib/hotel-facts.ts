import type { Hotel } from "./schema";

type Fact = { text: string; source: string };

export function summaryFacts(hotel: Hotel, facts: Fact[]): Fact[] {
  const place = (name?: string, kind?: string) =>
    name
      ? facts.find(
          (f) =>
            (f.text.startsWith(`${kind ? `${kind}: ` : ""}${name}: `) ||
              (kind && f.text.startsWith(`Nearest ${kind}: ${name},`))) &&
            /straight-line from hotel|computed distance/.test(f.text),
        )
      : undefined;
  return [
    place(hotel.nearest_metro?.name, "metro"),
    place(hotel.nearest_beach?.name, "beach"),
    ...[...hotel.landmarks]
      .sort((a, b) => a.metres - b.metres)
      .slice(0, 3)
      .map((p) => place(p.name)),
    facts.find((f) => f.text.startsWith("Proximity:")),
    facts.find((f) => /OSM stars tag|stars not tagged|stars, from the OSM/.test(f.text)),
    facts.find((f) => f.text.startsWith("Website:")),
  ].filter((f): f is Fact => !!f);
}

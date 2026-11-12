import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
const css = readFileSync("src/app/globals.css", "utf8");
function tokens(block: string) {
  return Object.fromEntries(
    [...block.matchAll(/--([a-z0-9-]+):\s*(#[a-f0-9]{6});/gi)].map((m) => [m[1], m[2]]),
  );
}
function luminance(hex: string) {
  const rgb = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}
function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
const light = tokens(css.slice(css.indexOf(":root {"), css.indexOf(':root[data-theme="dark"]')));
const dark = tokens(css.slice(css.indexOf(':root[data-theme="dark"]'), css.indexOf("* {")));
describe.each([
  ["light", light],
  ["dark", dark],
])("%s tokens", (_, t) => {
  it("defines all design tokens", () => expect(Object.keys(t)).toHaveLength(10));
  it.each(["ink", "ink-2", "ink-3", "alarm"])("%s text has 4.5:1 on every used background", (fg) => {
    for (const bg of ["page", "surface", "wash"])
      expect(contrast(t[fg], t[bg]), `${fg}/${bg}`).toBeGreaterThanOrEqual(4.5);
  });
  it("mismatch text is readable on alarm wash", () => {
    for (const fg of ["alarm", "ink", "ink-3"])
      expect(contrast(t[fg], t["alarm-wash"])).toBeGreaterThanOrEqual(4.5);
  });
  it("meaningful borders and glyphs have at least 3:1", () => {
    for (const fg of ["ink", "ink-3", "alarm"])
      for (const bg of ["page", "surface", "wash"]) expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(3);
  });
  it("filled controls have readable text", () => expect(contrast(t.page, t.ink)).toBeGreaterThanOrEqual(4.5));
});

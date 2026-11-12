import { describe, expect, it } from "vitest";
import { formatDistance } from "./distance";

describe("distance labels", () => {
  it.each([
    [0, "0 m"],
    [944, "940 m"],
    [945, "950 m"],
    [950, "950 m"],
    [999, "1000 m"],
    [1000, "1.0 km"],
    [5700, "5.7 km"],
    [5760, "5.8 km"],
  ])("formats %i metres as %s", (metres, label) => {
    expect(formatDistance(metres)).toBe(label);
  });
});

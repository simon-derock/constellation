import { describe, expect, it } from "vitest";
import { FIRST_DAY, HISTORY_SHARE, LAST_DAY, RAIL_DAYS, chartPosition, railIndex } from "./scale";

describe("RAIL_DAYS", () => {
  it("runs from the first day to the last, strictly increasing", () => {
    expect(RAIL_DAYS[0]).toBe(FIRST_DAY);
    expect(RAIL_DAYS.at(-1)).toBe(LAST_DAY);
    expect(RAIL_DAYS.every((day, i) => i === 0 || day > RAIL_DAYS[i - 1]!)).toBe(true);
  });

  it("offers every recorded day, so no recorded handover can be skipped", () => {
    for (let day = 0; day <= LAST_DAY; day += 1) expect(RAIL_DAYS).toContain(day);
  });

  it("samples the history sparsely", () => {
    expect(RAIL_DAYS.filter((day) => day < 0).length).toBeLessThan(80);
  });
});

describe("railIndex", () => {
  it("finds the exact position of a listed day and the nearest for any other", () => {
    expect(RAIL_DAYS[railIndex(30)]).toBe(30);
    expect(RAIL_DAYS[railIndex(-579)]).toBe(-579);
    expect(Math.abs(RAIL_DAYS[railIndex(-100)]! - -100)).toBeLessThanOrEqual(5);
    expect(railIndex(10_000)).toBe(RAIL_DAYS.length - 1);
    expect(railIndex(-10_000)).toBe(0);
  });
});

describe("chartPosition", () => {
  it("is 0 at the start, 1 at the end, and gives history only its narrow share", () => {
    expect(chartPosition(FIRST_DAY)).toBe(0);
    expect(chartPosition(LAST_DAY)).toBe(1);
    expect(chartPosition(0)).toBeCloseTo(HISTORY_SHARE, 10);
  });

  it("is strictly increasing across the whole range", () => {
    let previous = -1;
    for (let day = FIRST_DAY; day <= LAST_DAY; day += 1) {
      const position = chartPosition(day);
      expect(position).toBeGreaterThan(previous);
      previous = position;
    }
  });

  it("gives a recorded day far more room than a history day", () => {
    const recorded = chartPosition(11) - chartPosition(10);
    const history = chartPosition(-400) - chartPosition(-401);
    expect(recorded).toBeGreaterThan(history * 8);
  });

  it("clamps days outside the range instead of drawing off the chart", () => {
    expect(chartPosition(-1000)).toBe(0);
    expect(chartPosition(500)).toBe(1);
  });
});

import { describe, expect, it } from "vitest";
import { formationTargets } from "./formations";
import type { Formation } from "./types";

const NODES = Array.from({ length: 60 }, (_, i) => ({ id: `Person:p${i}` }));
const FORMATIONS: Formation[] = ["brain", "moon", "orbit", "culture"];

describe("formationTargets", () => {
  it.each(FORMATIONS)("places every node for %s, inside the figure", (formation) => {
    const targets = formationTargets(formation, NODES);
    expect(targets.size).toBe(NODES.length);
    for (const { x, y } of targets.values()) {
      expect(Number.isFinite(x) && Number.isFinite(y)).toBe(true);
      expect(Math.hypot(x, y)).toBeLessThan(1_000);
    }
  });

  it("is deterministic, so the same graph always takes the same shape", () => {
    const a = formationTargets("culture", NODES);
    const b = formationTargets("culture", NODES);
    expect([...a.entries()]).toEqual([...b.entries()]);
  });

  it("gives free layouts no targets, so the force simulation alone places them", () => {
    expect(formationTargets("free", NODES).size).toBe(0);
  });
});

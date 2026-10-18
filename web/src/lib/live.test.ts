import { describe, expect, it } from "vitest";
import { describeChange, secondsAt, tally, weekLabel } from "./live";

const ROWS = [
  { kind: "issue", state: "open", items: 1063 },
  { kind: "issue", state: "closed", items: 2759 },
  { kind: "pr", state: "merged", items: 3518 },
  { kind: "pr", state: "open", items: 396 },
];

describe("tally", () => {
  it("groups counts by kind and gives each kind a total", () => {
    const t = tally(ROWS);
    expect(t.issue).toEqual({ open: 1063, closed: 2759, merged: 0, total: 3822 });
    expect(t.pr).toEqual({ open: 396, closed: 0, merged: 3518, total: 3914 });
  });

  it("is empty, not undefined, when nothing was tracked yet", () => {
    expect(tally([]).issue.total).toBe(0);
    expect(tally(null).pr.total).toBe(0);
  });

  it("ignores states it does not know instead of inventing them", () => {
    expect(tally([{ kind: "issue", state: "weird", items: 5 }]).issue.total).toBe(0);
  });
});

describe("secondsAt", () => {
  const NOW = Date.UTC(2026, 9, 18, 12, 0, 0);

  it("steps back whole weeks from now", () => {
    expect(secondsAt(0, NOW)).toBe(NOW / 1000);
    expect(secondsAt(2, NOW)).toBe(NOW / 1000 - 2 * 7 * 86_400);
  });

  it("never goes before the epoch", () => {
    expect(secondsAt(100_000, NOW)).toBe(0);
  });
});

describe("weekLabel", () => {
  it("says now, then counts weeks, then gives the date", () => {
    expect(weekLabel(0)).toBe("Now");
    expect(weekLabel(1)).toBe("1 week ago");
    expect(weekLabel(12)).toBe("12 weeks ago");
  });
});

describe("describeChange", () => {
  it("reads a state change as a sentence", () => {
    expect(describeChange({ predicate: "state", old: "open", new: "merged" })).toBe("open → merged");
  });

  it("names added and removed labels instead of printing lists", () => {
    expect(describeChange({ predicate: "labels", old: "bug", new: "bug,p1" })).toBe("label added: p1");
    expect(describeChange({ predicate: "labels", old: "bug,p1", new: "bug" })).toBe("label removed: p1");
  });

  it("describes assignment without exposing more than the aliases", () => {
    expect(describeChange({ predicate: "assignees", old: "", new: "calm-otter-3f" })).toBe("assigned: calm-otter-3f");
    expect(describeChange({ predicate: "assignees", old: "calm-otter-3f", new: "" })).toBe("unassigned");
  });
});

import type { LiveChange, LiveStateRow } from "./api";

export interface Counts {
  open: number;
  closed: number;
  merged: number;
  total: number;
}

export type Tally = Record<"issue" | "pr", Counts>;

const empty = (): Counts => ({ open: 0, closed: 0, merged: 0, total: 0 });

// counts per kind and state; unknown kinds or states are dropped, so the totals only ever sum what the graph said
export function tally(rows: readonly LiveStateRow[] | null): Tally {
  const out: Tally = { issue: empty(), pr: empty() };
  for (const row of rows ?? []) {
    if ((row.kind !== "issue" && row.kind !== "pr") || !(row.state in out.issue)) continue;
    const counts = out[row.kind];
    counts[row.state as "open" | "closed" | "merged"] += row.items;
    counts.total += row.items;
  }
  return out;
}

const WEEK = 7 * 86_400;

// the slider counts whole weeks back from now; the server takes epoch seconds
export function secondsAt(weeksAgo: number, nowMs: number = Date.now()): number {
  return Math.max(0, Math.floor(nowMs / 1000) - weeksAgo * WEEK);
}

export function weekLabel(weeksAgo: number): string {
  if (weeksAgo === 0) return "Now";
  return `${weeksAgo} ${weeksAgo === 1 ? "week" : "weeks"} ago`;
}

const split = (value: string) => (value ? value.split(",") : []);

export function describeChange(change: Pick<LiveChange, "predicate" | "old" | "new">): string {
  if (change.predicate === "state") return `${change.old} → ${change.new}`;
  const before = split(change.old);
  const after = split(change.new);
  const added = after.filter((v) => !before.includes(v));
  const removed = before.filter((v) => !after.includes(v));
  if (change.predicate === "labels") {
    if (added.length) return `label added: ${added.join(", ")}`;
    return `label removed: ${removed.join(", ")}`;
  }
  return added.length ? `assigned: ${added.join(", ")}` : "unassigned";
}

export function dayLabel(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

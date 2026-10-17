export interface Interval {
  owner: string;
  from: number;
  // absent while the ownership is still open
  to: number | null;
  origin: "claim" | "former_owner" | "registry_snapshot";
  start_known: boolean;
  evidence: string;
}

export interface DomainTimeline {
  domain: string;
  intervals: Interval[];
}

// half-open [from, to): on a handover day the new holder answers; a gap between holders is nobody
export function ownerAt(intervals: readonly Interval[], day: number): Interval | undefined {
  return intervals.find((i) => i.from <= day && (i.to === null || day < i.to));
}

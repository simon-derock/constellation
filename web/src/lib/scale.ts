// Apex runs from simulation day -579 (before the company's records start) to day 60
export const FIRST_DAY = -579;
export const LAST_DAY = 60;

// the recorded days are where ownership changes; history is context, so it gets a narrow band of the chart
export const HISTORY_SHARE = 0.16;

// every recorded day, but only every tenth day of history: each step of the rail is a change worth seeing
export const RAIL_DAYS: readonly number[] = [
  FIRST_DAY,
  ...Array.from({ length: 57 }, (_, i) => -570 + i * 10),
  ...Array.from({ length: LAST_DAY + 1 }, (_, i) => i),
];

export function railIndex(day: number): number {
  let best = 0;
  RAIL_DAYS.forEach((candidate, i) => {
    if (Math.abs(candidate - day) < Math.abs(RAIL_DAYS[best]! - day)) best = i;
  });
  return best;
}

// 0 at the first day, 1 at the last; piecewise linear, steeper over the recorded days
export function chartPosition(day: number): number {
  const clamped = Math.min(Math.max(day, FIRST_DAY), LAST_DAY);
  if (clamped <= 0) return (HISTORY_SHARE * (clamped - FIRST_DAY)) / -FIRST_DAY;
  return HISTORY_SHARE + ((1 - HISTORY_SHARE) * clamped) / LAST_DAY;
}

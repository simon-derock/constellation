import { useAsOf } from "../asof";
import { ownerAt, type DomainTimeline } from "../lib/ownership";
import { chartPosition, LAST_DAY } from "../lib/scale";

const LABEL = 150;
const WIDTH = 1000;
const ROW = 34;
const PLOT = WIDTH - LABEL;

// history is a narrow band and the recorded days get the room, because that is where ownership changes
const x = (day: number): number => LABEL + chartPosition(day) * PLOT;

// who owned each domain across the simulation, drawn as intervals; the cursor is the as-of day
export function OwnershipChart({ domains }: { domains: DomainTimeline[] }) {
  const { day } = useAsOf();
  const height = domains.length * ROW + 44;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} role="img" aria-label="Ownership of each domain over time">
        <defs>
          <pattern id="unknown-start" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--sheet)" />
            <rect width="2.5" height="6" fill="var(--stale)" />
          </pattern>
        </defs>
        {domains.map((domain, row) => {
          const top = row * ROW + 6;
          return (
            <g key={domain.domain}>
              <text x={0} y={top + 19} className="chart-label">
                {domain.domain}
              </text>
              <line x1={LABEL} x2={WIDTH} y1={top + 28} y2={top + 28} className="chart-rule" />
              {domain.intervals.map((span) => {
                const left = x(span.from);
                const right = span.to === null ? x(LAST_DAY) : x(span.to);
                const wide = right - left > 56;
                return (
                  <g key={`${span.owner}-${span.from}`}>
                    <rect
                      x={left}
                      y={top + 4}
                      width={Math.max(right - left, 2)}
                      height={20}
                      rx={2}
                      className={`bar bar-${span.origin}`}
                      fill={span.origin === "registry_snapshot" ? "url(#unknown-start)" : undefined}
                    >
                      <title>{`${span.owner}, from day ${span.from < -900 ? "before records" : span.from}${
                        span.to === null ? " (open)" : ` to day ${span.to}`
                      }. ${span.start_known ? "Start recorded." : "Start not recorded."}`}</title>
                    </rect>
                    {wide && (
                      <text x={left + 8} y={top + 18} className="bar-text">
                        {span.owner}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
        <line x1={x(0)} x2={x(0)} y1={0} y2={height - 34} className="zero" />
        <text x={x(0)} y={height - 20} textAnchor="middle" className="axis-label">
          day 0
        </text>
        <text x={LABEL} y={height - 20} className="axis-label">
          before the records
        </text>
        <line x1={x(day)} x2={x(day)} y1={0} y2={height - 34} className="cursor" />
        <text x={Math.min(Math.max(x(day), LABEL + 24), WIDTH - 24)} y={height - 4} textAnchor="middle" className="cursor-label">
          day {day}
        </text>
      </svg>

      <dl className="now" aria-label={`Owners on day ${day}`}>
        {domains.map((domain) => {
          const holder = ownerAt(domain.intervals, day);
          return (
            <div key={domain.domain}>
              <dt>{domain.domain}</dt>
              <dd className={holder ? undefined : "nobody"}>
                {holder ? holder.owner : "Nobody on record"}
                {holder && !holder.start_known && <span className="note"> since an unrecorded day</span>}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

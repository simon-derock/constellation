import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ProofPanel } from "../components/ProofPanel";
import { type LiveStateRow, live } from "../lib/api";
import { type Counts, dayLabel, describeChange, secondsAt, tally, weekLabel } from "../lib/live";

const TENANT = "falkordb";
const MAX_WEEKS = 104;

function Bar({ label, counts }: { label: string; counts: Counts }) {
  const share = (n: number) => (counts.total ? `${(100 * n) / counts.total}%` : "0%");
  return (
    <div className="tally">
      <div className="tally-head">
        <span>{label}</span>
        <strong>{counts.total.toLocaleString()}</strong>
      </div>
      <div className="tally-bar" role="img" aria-label={`${counts.open} open, ${counts.merged} merged, ${counts.closed} closed`}>
        <i className="seg open" style={{ width: share(counts.open) }} />
        <i className="seg merged" style={{ width: share(counts.merged) }} />
        <i className="seg closed" style={{ width: share(counts.closed) }} />
      </div>
      <p className="tally-nums">
        {counts.open.toLocaleString()} open · {counts.merged.toLocaleString()} merged · {counts.closed.toLocaleString()} closed
      </p>
    </div>
  );
}

function Pair({ title, rows }: { title: string; rows: LiveStateRow[] | null }) {
  const t = tally(rows);
  return (
    <div className="tallies" aria-label={title}>
      <Bar label="Issues" counts={t.issue} />
      <Bar label="Pull requests" counts={t.pr} />
    </div>
  );
}

// FalkorDB's own public GitHub, read through the same graph and proofs as every other tenant; the slider is the
// bitemporal part: the graph keeps every claim with the span it held, so "as of" is a query, not a backup
export function LiveView() {
  const [weeks, setWeeks] = useState(0);
  const openedAt = useMemo(() => Date.now(), []);
  const at = weeks === 0 ? undefined : secondsAt(weeks, openedAt);
  const view = useQuery({
    queryKey: ["live", TENANT, at],
    queryFn: () => live(TENANT, at),
    placeholderData: keepPreviousData,
  });
  const data = view.data;
  const newest = data?.freshness.newest ? Date.parse(data.freshness.newest) / 1000 : null;
  const sealKey = data?.proof.queries.map((q) => q.sha256).join("") ?? "";

  return (
    <div className="page" data-ghost="Live">
      <h1>FalkorDB, on any day</h1>
      <p className="lede">Every public issue and pull request, as it stood. People appear only as aliases.</p>

      {view.isPending && <p className="hint">Loading the organisation…</p>}
      {view.error && !data && (
        <p className="result bad" role="alert">
          The live data could not be loaded. Check that the server is running and try again.
        </p>
      )}

      {data && (
        <>
          <p className="hint">
            {data.freshness.repositories} repositories synced
            {newest !== null && <>, newest change on {dayLabel(newest)}</>}.
          </p>

          <section className="timetravel" aria-label="Time travel">
            <label className="field-label" htmlFor="weeks">
              Showing {weekLabel(weeks)}
              {at !== undefined && <> ({dayLabel(at)})</>}
            </label>
            <input
              id="weeks"
              type="range"
              min={0}
              max={MAX_WEEKS}
              step={1}
              value={weeks}
              onChange={(e) => setWeeks(Number(e.target.value))}
              aria-valuetext={weekLabel(weeks)}
            />
            <div className="rail-ends">
              <span>Two years ago</span>
              <span>Now</span>
            </div>
          </section>

          {data.as_of ? (
            <>
              <h2>{weekLabel(weeks)}</h2>
              <Pair title="State in the past" rows={data.as_of} />
              <h2>Now</h2>
            </>
          ) : (
            <h2>Now</h2>
          )}
          <Pair title="State now" rows={data.summary} />

          <h2>Latest changes</h2>
          <ul className="changes">
            {data.changes.map((c) => (
              <li key={`${c.item}-${c.predicate}-${c.at}`}>
                <span className="change-item">{c.item}</span>
                <span className="change-title">{c.title}</span>
                <span className="change-what">{describeChange(c)}</span>
                <time dateTime={new Date(c.at * 1000).toISOString()}>{dayLabel(c.at)}</time>
              </li>
            ))}
            {data.changes.length === 0 && <li className="hint">No changes seen since the first sync.</li>}
          </ul>

          <h2>Busiest repositories</h2>
          <ol className="repos">
            {data.repos.map((r) => (
              <li key={r.repo}>
                <span>{r.repo}</span>
                <b>{r.items.toLocaleString()}</b>
              </li>
            ))}
          </ol>

          <ProofPanel key={sealKey} tenant={TENANT} queries={data.proof.queries} />
        </>
      )}
    </div>
  );
}

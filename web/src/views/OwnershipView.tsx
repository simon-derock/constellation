import { useQuery } from "@tanstack/react-query";
import { OwnershipChart } from "../components/OwnershipChart";
import { ownership } from "../lib/api";

export function OwnershipView() {
  const timeline = useQuery({ queryKey: ["ownership", "apex"], queryFn: () => ownership("apex") });
  return (
    <div className="page">
      <h1>Who owned what, on any day</h1>
      <p className="lede">
        Each bar is one owner of one domain. Move the time rail to see who held each domain on a given day. A handover
        day belongs to the new owner, and a gap means nobody was on record.
      </p>
      {timeline.isPending && <p className="hint">Loading ownership…</p>}
      {timeline.error && (
        <p className="result bad" role="alert">
          Ownership could not be loaded. Check that the server is running and try again.
        </p>
      )}
      {timeline.data && (
        <>
          <OwnershipChart domains={timeline.data.domains} />
          <ul className="key" aria-label="Legend">
            <li>
              <i className="swatch claim" /> Claimed ownership, with its day recorded
            </li>
            <li>
              <i className="swatch former" /> Earlier owner, until their departure
            </li>
            <li>
              <i className="swatch unknown" /> Owner on the final snapshot; the start day was never recorded
            </li>
          </ul>
          <p className="hint">
            Read from one query, result hash{" "}
            <code>{timeline.data.proof.queries[0]?.sha256.slice(0, 16)}…</code>
          </p>
        </>
      )}
    </div>
  );
}

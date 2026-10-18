import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ProofPanel } from "../components/ProofPanel";
import { liveSearch, livePeople, type SearchHit } from "../lib/api";

const VIA: Record<string, string> = { vector: "meaning", text: "words" };

// the live graph, searched by meaning and by words, with the people the graph's algorithms rank most connected
export function LiveSearch() {
  const [draft, setDraft] = useState("");
  const search = useMutation({ mutationFn: (q: string) => liveSearch(q) });
  const people = useQuery({ queryKey: ["live-people"], queryFn: livePeople, retry: false });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const q = draft.trim();
    if (q) search.mutate(q);
  };

  return (
    <section className="live-search" aria-label="Search the live graph">
      <p className="label center">Search the live graph</p>
      <form onSubmit={submit} className="live-search-form" role="search">
        <label htmlFor="live-q" className="sr-only">
          Ask the live graph
        </label>
        <input
          id="live-q"
          type="search"
          value={draft}
          maxLength={200}
          placeholder="What is the crash on restart about?"
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="primary" disabled={search.isPending || draft.trim() === ""}>
          {search.isPending ? "Searching" : "Search"}
        </button>
      </form>

      {search.isError && (
        <p className="result bad" role="alert">
          The search could not run. Try again in a moment.
        </p>
      )}
      {search.data && (
        <>
          <p className="hint center">
            {search.data.vector_used ? "Matched by meaning and by words" : "Matched by words only"}
          </p>
          {search.data.hits.length === 0 ? (
            <p className="hint center">Nothing in the live graph matched.</p>
          ) : (
            <ol className="hits">
              {search.data.hits.map((h: SearchHit) => (
                <li key={h.item}>
                  <span className="hit-title">{h.title}</span>
                  <span className="hit-meta">
                    {h.item} · {h.via.map((v) => VIA[v] ?? v).join(" + ")}
                  </span>
                </li>
              ))}
            </ol>
          )}
          {search.data.proof.queries.length > 0 && (
            <ProofPanel tenant="falkordb" queries={search.data.proof.queries} />
          )}
        </>
      )}

      {Array.isArray(people.data?.central) && Array.isArray(people.data?.bridges) && (
        <div className="people">
          <p className="label center">Most connected</p>
          <ol className="people-list">
            {people.data.central.slice(0, 5).map((p) => (
              <li key={p.person}>
                <span>{p.person}</span>
                <span className="hit-meta">{p.score.toFixed(4)}</span>
              </li>
            ))}
          </ol>
          <p className="label center">Bridges between others</p>
          <ol className="people-list">
            {people.data.bridges.slice(0, 5).map((p) => (
              <li key={p.person}>
                <span>{p.person}</span>
                <span className="hit-meta">{p.score.toFixed(0)}</span>
              </li>
            ))}
          </ol>
          {people.data?.components?.[0] && (
            <p className="hint center">
              The largest connected group holds {people.data.components[0]!.size.toLocaleString()} people.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

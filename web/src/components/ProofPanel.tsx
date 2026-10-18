import { useMutation } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, type ProofQuery, replay } from "../lib/api";
import { sealHash } from "../lib/bits";
import { BitGrid } from "./BitGrid";

interface Props {
  tenant: string;
  queries: ProofQuery[];
}

const short = (hash: string) => `${hash.slice(0, 12)}…`;

// everything needed to check an answer: the exact queries, their result hashes, and a replay that must reproduce
// the hashes bit for bit
export function ProofPanel({ tenant, queries }: Props) {
  const hashes = queries.map((q) => q.sha256);
  const [seal, setSeal] = useState<string>();
  useEffect(() => {
    let current = true;
    void sealHash(hashes).then((value) => current && setSeal(value));
    return () => {
      current = false;
    };
    // the seal is a function of the queries, which never mutate; the joined key keeps the dependency primitive
  }, [hashes.join("")]); // eslint-disable-line react-hooks/exhaustive-deps

  const check = useMutation({
    mutationFn: async () => {
      const result = await replay({ tenant, queries });
      return { result, seal: await sealHash(result.results.map((r) => r.sha256)) };
    },
  });
  const matches = check.data?.result.results.filter((r) => r.match).length ?? 0;
  const total = queries.length;
  const verified = check.data?.result.all_match === true;

  return (
    <section className="proof" aria-label="Proof">
      <div className="seal">
        {seal && <BitGrid hash={seal} replayed={check.data?.seal} label="Proof seal" />}
        <div className="seal-copy">
          <button type="button" className="replay" onClick={() => check.mutate()} disabled={check.isPending}>
            {check.isPending ? "Replaying…" : "Replay proof"}
          </button>
          {check.data && (
            <p className={verified ? "result ok" : "result bad"} role="status">
              {verified
                ? `Verified: ${matches} of ${total} queries returned identical results.`
                : `Not verified: ${total - matches} of ${total} queries returned a different result.`}
            </p>
          )}
          {check.error && (
            <p className="result bad" role="alert">
              {check.error instanceof ApiError ? check.error.message : "The replay failed. Try again."}
            </p>
          )}
          <p className="hint">Replay re-runs every query read-only. The seal is the SHA-256 of their result hashes.</p>
        </div>
      </div>

      <ol className="queries">
        {queries.map((q, i) => {
          const outcome = check.data?.result.results[i];
          return (
            <li key={`${q.name}-${i}`}>
              <span className="query-name">{q.name}</span>
              <code className="query-params">{JSON.stringify(q.params)}</code>
              <code className="query-hash" title={q.sha256}>
                {short(q.sha256)}
              </code>
              {outcome && <span className={outcome.match ? "match" : "differs"}>{outcome.match ? "matches" : "differs"}</span>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}


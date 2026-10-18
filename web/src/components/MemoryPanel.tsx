import { useQuery } from "@tanstack/react-query";
import { ApiError, memory } from "../lib/api";

interface Props {
  tenant: string;
  session: string;
  // the panel reads memory only once a question has been asked, so a page load costs the server nothing
  enabled: boolean;
}

const short = (hash: string) => `${hash.slice(0, 12)}…`;
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

// what this session asked, and what the system has learned from it; shown only for this session's own questions
export function MemoryPanel({ tenant, session, enabled }: Props) {
  const view = useQuery({ queryKey: ["memory", tenant, session], queryFn: () => memory(tenant, session), enabled, retry: false });

  if (view.error) {
    return (
      <section className="memory" aria-label="Memory">
        <p className="label">Memory</p>
        <p className="hint">{view.error instanceof ApiError ? view.error.message : "Memory could not be read. Try again."}</p>
      </section>
    );
  }
  if (!view.data || (view.data.turns.length === 0 && view.data.facts.length === 0)) return null;
  const { turns, facts, procedures } = view.data;

  return (
    <section className="memory" aria-label="Memory">
      <p className="label">Memory</p>
      <p className="hint">Kept for this session. A repeated question is answered from memory only after its proof replays on the graph.</p>

      <p className="label small">This session</p>
      <ol className="turns">
        {turns.map((turn) => (
          <li key={turn.n}>
            <span className="turn-role">{turn.role === "user" ? "You" : "Answer"}</span>
            <span className="turn-text">{turn.content}</span>
            {turn.seal && (
              <code className="query-hash" title={turn.seal}>
                {short(turn.seal)}
              </code>
            )}
          </li>
        ))}
      </ol>

      <p className="label small">Learned</p>
      {facts.length === 0 ? (
        <p className="hint">Nothing learned yet. A fact needs two answers that agree and none that disagree.</p>
      ) : (
        <ul className="learned">
          {facts.map((fact, i) => (
            // the same words can be asked as two kinds of question, so the position is part of the identity
            <li key={`${i}-${fact.kind}`}>
              <p className="fact-verdict">{fact.verdict}</p>
              <p className="fact-question">{fact.question}</p>
              <p className="fact-meta">
                Confirmed by {plural(fact.support, "answer", "answers")}, on {plural(fact.evidence.length, "result hash", "result hashes")}.
              </p>
              <ul className="hashes" aria-label="Evidence">
                {fact.evidence.map((hash) => (
                  <li key={hash}>
                    <code className="query-hash" title={hash}>
                      {short(hash)}
                    </code>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}

      <p className="hint">
        {plural(procedures, "procedure", "procedures")} stored. Each is replayed against the graph before it is reused.
      </p>
    </section>
  );
}

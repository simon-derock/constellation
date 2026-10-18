import { type AskResponse } from "../lib/api";
import { describeAnswer } from "../lib/answer";
import { ProofPanel } from "./ProofPanel";

interface Props {
  response: AskResponse;
}

// the answer, and beneath it the proof that lets anyone check it
export function ProofSheet({ response }: Props) {
  const described = describeAnswer(response.kind, response.answer);
  return (
    <article className="sheet" aria-label="Answer and proof">
      <h2 className="verdict">{described.verdict}</h2>
      {described.detail && <p className="detail">{described.detail}</p>}
      {described.evidence.length > 0 && (
        <ul className="evidence" aria-label="Evidence">
          {described.evidence.map((id) => (
            <li key={id}>{id}</li>
          ))}
        </ul>
      )}

      <ProofPanel tenant={response.tenant} queries={response.proof.queries} />

      <p className="cost">
        {response.trace.llm_calls} model {response.trace.llm_calls === 1 ? "call" : "calls"},{" "}
        {(response.trace.prompt_tokens + response.trace.completion_tokens).toLocaleString()} tokens. Everything else was
        read from the graph.
      </p>
    </article>
  );
}

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

      {response.proposed_action && (
        <p className="proposed">
          <span className="label small">Proposed by the agent</span>
          <span className="proposed-title">{response.proposed_action.title}</span>
          <a href="#act">Review it under Act</a>
        </p>
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

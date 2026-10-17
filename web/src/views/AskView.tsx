import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useAsOf } from "../asof";
import { ProofSheet } from "../components/ProofSheet";
import { actors, ApiError, ask, type Kind } from "../lib/api";

const TENANT = "apex";

const MODES: { kind: Kind; label: string; hint: string }[] = [
  { kind: "PERSPECTIVE", label: "Who could have known?", hint: "Answered from one person's point of view, as of the day on the time rail." },
  { kind: "COUNTERFACTUAL", label: "What if it hadn't happened?", hint: "Traces a cause to its effect and asks whether the effect needed it." },
  { kind: "SILENCE", label: "Did it happen?", hint: "Checks for an expected follow-up and reports everything it searched." },
];

const EXAMPLES: { kind: Kind; actor?: string; day?: number; text: string }[] = [
  { kind: "SILENCE", text: "Was a Salesforce risk flag raised after the Day 8 incident involving Jax and Kaitlyn?" },
  {
    kind: "COUNTERFACTUAL",
    text: "If the documentation gap in the design doc that Jax contributed to on Day 4 had not existed, would the incident still have occurred?",
  },
  { kind: "PERSPECTIVE", actor: "Alex", day: 28, text: "Would Alex have learned about the incident resolved event through normal channels by Day 28?" },
];

export function AskView() {
  const { day, setDay } = useAsOf();
  const [kind, setKind] = useState<Kind>("SILENCE");
  const [question, setQuestion] = useState("");
  const [actor, setActor] = useState("");
  const people = useQuery({ queryKey: ["actors", TENANT], queryFn: () => actors(TENANT), staleTime: Infinity });
  const asked = useMutation({ mutationFn: ask });
  const chosen = actor || people.data?.actors[0]?.name || "";
  const mode = MODES.find((m) => m.kind === kind)!;

  function submit(event: FormEvent) {
    event.preventDefault();
    asked.mutate({
      tenant: TENANT,
      kind,
      question: question.trim(),
      ...(kind === "PERSPECTIVE" ? { actor: chosen, day } : {}),
    });
  }

  return (
    <div className="ask">
      <form onSubmit={submit} className="ask-form">
        <h1>Ask a question. Get an answer you can check.</h1>
        <p className="lede">
          Every answer lists the exact queries behind it. Replay them and the proof seal must match, bit for bit.
        </p>

        <fieldset className="modes">
          <legend>What are you asking?</legend>
          {MODES.map((m) => (
            <label key={m.kind} className={m.kind === kind ? "mode on" : "mode"}>
              <input type="radio" name="kind" value={m.kind} checked={m.kind === kind} onChange={() => setKind(m.kind)} />
              {m.label}
            </label>
          ))}
          <p className="hint">{mode.hint}</p>
        </fieldset>

        {kind === "PERSPECTIVE" && (
          <div className="viewas">
            <label htmlFor="actor">View as</label>
            <select id="actor" value={chosen} onChange={(e) => setActor(e.target.value)} disabled={!people.data}>
              {people.data?.actors.map((a) => (
                <option key={a.name} value={a.name}>
                  {a.name} ({a.role.replaceAll("_", " ")})
                </option>
              ))}
            </select>
            <span className="hint">Answers use only what this person could see by day {day}.</span>
          </div>
        )}

        <label htmlFor="question" className="field-label">
          Your question
        </label>
        <textarea
          id="question"
          value={question}
          maxLength={600}
          rows={4}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Write it the way you would ask a colleague."
        />

        <div className="actions">
          <button type="submit" className="primary" disabled={asked.isPending || question.trim().length === 0}>
            {asked.isPending ? "Asking…" : "Ask"}
          </button>
          <span className="count">{question.length} of 600</span>
        </div>

        <div className="examples">
          <p className="hint">Or start from an example:</p>
          <ul>
            {EXAMPLES.map((example) => (
              <li key={example.text}>
                <button
                  type="button"
                  className="link"
                  onClick={() => {
                    setKind(example.kind);
                    setQuestion(example.text);
                    if (example.actor) setActor(example.actor);
                    if (example.day !== undefined) setDay(example.day);
                  }}
                >
                  {example.text}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </form>

      <section className="ask-result" aria-live="polite">
        {asked.error && (
          <p className="result bad" role="alert">
            {asked.error instanceof ApiError ? asked.error.message : "Something went wrong. Try asking again."}
          </p>
        )}
        {asked.data ? (
          <ProofSheet response={asked.data} />
        ) : (
          !asked.error && (
            <div className="empty">
              <h2>Nothing asked yet</h2>
              <p>Pick an example or write a question. The answer arrives with the queries that produced it.</p>
            </div>
          )
        )}
      </section>
    </div>
  );
}

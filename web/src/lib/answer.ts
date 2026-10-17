import type { Kind } from "./api";

export interface Described {
  verdict: string;
  detail: string;
  evidence: string[];
}

const words = (label: string): string => label.replaceAll("_", " ");
const list = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);

// the same answer in words a reader can act on; a missing or malformed verdict is stated as such, never guessed
export function describeAnswer(kind: Kind, answer: Record<string, unknown>): Described {
  const none: Described = { verdict: "No verdict was reached.", detail: "", evidence: [] };
  if (kind === "SILENCE") {
    if (typeof answer.exists !== "boolean") return none;
    return {
      verdict: answer.exists ? "Yes, it happened." : "No, it did not happen.",
      detail: String(answer.reasoning ?? ""),
      evidence: [],
    };
  }
  if (kind === "PERSPECTIVE") {
    if (typeof answer.could_actor_have_known !== "boolean") return none;
    const blocked = list(answer.blocked_subsystems);
    return {
      verdict: answer.could_actor_have_known ? "Could have known." : "Could not have known.",
      detail: blocked.length ? `Not open to this role: ${blocked.join(", ")}.` : "",
      evidence: list(answer.evidence_artifacts),
    };
  }
  if (typeof answer.outcome_changed !== "boolean") return none;
  const mechanism = answer.causal_mechanism ? `Link: ${words(String(answer.causal_mechanism))}.` : "";
  const people = list(answer.actors);
  return {
    verdict: answer.outcome_changed ? "The outcome would have changed." : "The outcome would still have happened.",
    detail: [mechanism, people.length ? `People involved: ${people.join(", ")}.` : ""].filter(Boolean).join(" "),
    evidence: [],
  };
}

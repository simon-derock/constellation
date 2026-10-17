import { describe, expect, it } from "vitest";
import { describeAnswer } from "./answer";

describe("describeAnswer", () => {
  it("states an absence plainly and keeps the searched trail as detail", () => {
    const out = describeAnswer("SILENCE", { exists: false, reasoning: "Searched 2 artifacts." });
    expect(out.verdict).toBe("No, it did not happen.");
    expect(out.detail).toBe("Searched 2 artifacts.");
  });

  it("says who could have known and lists evidence and blocked subsystems", () => {
    const yes = describeAnswer("PERSPECTIVE", {
      could_actor_have_known: true,
      evidence_artifacts: ["ENG-173", "PR-129"],
    });
    expect(yes.verdict).toBe("Could have known.");
    expect(yes.evidence).toEqual(["ENG-173", "PR-129"]);
    const no = describeAnswer("PERSPECTIVE", { could_actor_have_known: false, blocked_subsystems: ["git"] });
    expect(no.verdict).toBe("Could not have known.");
    expect(no.detail).toContain("git");
  });

  it("explains a counterfactual in terms of the outcome", () => {
    const out = describeAnswer("COUNTERFACTUAL", {
      outcome_changed: false,
      causal_mechanism: "doc_gap_detected",
      actors: ["Jax", "Raj"],
    });
    expect(out.verdict).toBe("The outcome would still have happened.");
    expect(out.detail).toContain("doc gap detected");
    expect(out.detail).toContain("Jax, Raj");
  });

  it("is honest when the system returned no verdict", () => {
    expect(describeAnswer("SILENCE", {}).verdict).toBe("No verdict was reached.");
    expect(describeAnswer("COUNTERFACTUAL", { outcome_changed: "maybe" }).verdict).toBe("No verdict was reached.");
  });
});

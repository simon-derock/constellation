import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AsOfProvider } from "../asof";
import { AskView } from "./AskView";

const HASH = "a".repeat(64);
const answer = (extra: object) => ({
  tenant: "apex",
  kind: "SILENCE",
  answer: { exists: false, reasoning: "Searched 2 artifacts." },
  proof: { queries: [{ name: "absence", params: {}, sha256: HASH }] },
  trace: { stop_reason: "planned", strategy_changes: [], llm_calls: 2, prompt_tokens: 600, completion_tokens: 40, tools: [] },
  ...extra,
});
const PROPOSED = {
  id: "p1",
  kind: "file_issue",
  title: "Write the postmortem for the Day 8 incident",
  body: "",
  status: "proposed",
  approver: null,
  mode: null,
  result: null,
  evidence: [{ name: "absence", params: {}, sha256: HASH }],
  created: "t",
  provenance: "agent",
  payload_hash: "b".repeat(64),
};

function show(reply: object) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("/actors") ? { actors: [] } : reply), { status: 200 })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <AsOfProvider>
        <AskView />
      </AsOfProvider>
    </QueryClientProvider>,
  );
  return invalidate;
}

async function ask() {
  await userEvent.type(screen.getByLabelText("Your question"), "Was a risk flag raised?");
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

afterEach(() => vi.unstubAllGlobals());

describe("AskView", () => {
  it("shows the agent's proposal under the answer and refreshes the Act list", async () => {
    const invalidate = show(answer({ proposed_action: PROPOSED }));
    await ask();
    expect(await screen.findByText("Proposed by the agent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review it under Act" })).toHaveAttribute("href", "#act");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["actions"] });
  });

  it("leaves the Act list alone when the answer carries no proposal", async () => {
    const invalidate = show(answer({}));
    await ask();
    expect(await screen.findByText("No, it did not happen.")).toBeInTheDocument();
    expect(screen.queryByText("Proposed by the agent")).not.toBeInTheDocument();
    expect(invalidate).not.toHaveBeenCalled();
  });
});

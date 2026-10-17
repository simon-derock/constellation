import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AskResponse } from "../lib/api";
import { ProofSheet } from "./ProofSheet";

const H1 = "a".repeat(64);
const H2 = "b".repeat(64);

const response: AskResponse = {
  tenant: "apex",
  kind: "SILENCE",
  answer: { exists: false, reasoning: "Searched 2 artifacts." },
  proof: {
    queries: [
      { name: "absence", params: { trigger: "EVT-8" }, sha256: H1 },
      { name: "event_artifacts", params: { event: "EVT-8" }, sha256: H2 },
    ],
  },
  trace: { stop_reason: "planned", strategy_changes: [], llm_calls: 1, prompt_tokens: 600, completion_tokens: 40, tools: [] },
};

function show() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProofSheet response={response} />
    </QueryClientProvider>,
  );
}

function replyWith(hashes: string[], status = 200) {
  const results = hashes.map((sha256, i) => ({ name: response.proof.queries[i]!.name, match: sha256 === (i === 0 ? H1 : H2), sha256 }));
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ all_match: results.every((r) => r.match), results }), { status })));
}

afterEach(() => vi.unstubAllGlobals());

describe("ProofSheet", () => {
  it("states the verdict in words and shows the queries behind it", async () => {
    show();
    expect(screen.getByText("No, it did not happen.")).toBeInTheDocument();
    expect(screen.getByText("absence")).toBeInTheDocument();
    expect(screen.getByText("event_artifacts")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /Proof seal/ })).toBeInTheDocument();
  });

  it("verifies when the replay returns the same hashes", async () => {
    replyWith([H1, H2]);
    show();
    await userEvent.click(screen.getByRole("button", { name: "Replay proof" }));
    expect(await screen.findByText(/Verified: 2 of 2 queries returned identical results/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("img", { name: /identical bits/ })).toBeInTheDocument());
  });

  it("names the query whose result changed and flags the seal", async () => {
    replyWith([H1, "c".repeat(64)]);
    show();
    await userEvent.click(screen.getByRole("button", { name: "Replay proof" }));
    expect(await screen.findByText(/Not verified: 1 of 2 queries returned a different result/)).toBeInTheDocument();
    expect(screen.getByText("differs")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("img", { name: /differs in \d+ of 256 bits/ })).toBeInTheDocument());
  });

  it("explains an unreachable server instead of showing a verdict", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("network"))));
    show();
    await userEvent.click(screen.getByRole("button", { name: "Replay proof" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach the server/);
    expect(screen.queryByText(/Verified/)).not.toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MemoryView } from "../lib/api";
import { MemoryPanel } from "./MemoryPanel";

const SESSION = "11111111-aaaa-4bbb-8ccc-222222222222";
const SEAL = "c".repeat(64);
const EVIDENCE = "d".repeat(64);

const learned: MemoryView = {
  session: SESSION,
  turns: [
    { n: 1, role: "user", content: "Was a risk flag raised after the Day 8 incident?", seal: "" },
    { n: 2, role: "assistant", content: "No, it did not happen.", seal: SEAL },
  ],
  facts: [
    {
      question: "Was a risk flag raised after the Day 8 incident?",
      kind: "SILENCE",
      verdict: "No, it did not happen.",
      support: 2,
      evidence: [EVIDENCE],
    },
  ],
  procedures: 1,
};

function serve(body: MemoryView | null, status = 200) {
  const fetcher = vi.fn(async (_url: string) => new Response(JSON.stringify(body ?? { detail: "memory is not enabled on this server" }), { status }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function show(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryPanel tenant="apex" session={SESSION} enabled={enabled} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("MemoryPanel", () => {
  it("lists this session's turns and, for an answer, the seal of its proof", async () => {
    serve(learned);
    show();
    expect(await screen.findByText("You")).toBeInTheDocument();
    expect(screen.getByText("Answer")).toBeInTheDocument();
    expect(screen.getByTitle(SEAL)).toHaveTextContent(`${"c".repeat(12)}…`);
  });

  it("shows what has been learned with how many answers agree and the evidence behind it", async () => {
    serve(learned);
    show();
    expect(await screen.findByText("Confirmed by 2 answers, on 1 result hash.")).toBeInTheDocument();
    const evidence = screen.getByRole("list", { name: "Evidence" });
    expect(within(evidence).getByTitle(EVIDENCE)).toHaveTextContent(`${"d".repeat(12)}…`);
    expect(screen.getByText(/1 procedure stored/)).toBeInTheDocument();
  });

  it("says nothing has been learned until two answers agree", async () => {
    serve({ ...learned, facts: [], procedures: 2 });
    show();
    expect(await screen.findByText(/Nothing learned yet/)).toBeInTheDocument();
    expect(screen.getByText(/2 procedures stored/)).toBeInTheDocument();
  });

  it("asks the server for this session and tenant only", async () => {
    const fetcher = serve(learned);
    show();
    await screen.findByText("You");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/v1/memory?tenant=apex&session=${SESSION}`);
  });

  it("reads nothing until a question has been asked", () => {
    const fetcher = serve(learned);
    show(false);
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Memory" })).not.toBeInTheDocument();
  });

  it("shows nothing for a session with no turns", async () => {
    const fetcher = serve({ ...learned, turns: [], facts: [] });
    show();
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Memory" })).not.toBeInTheDocument();
  });

  it("says why memory is unavailable instead of failing silently", async () => {
    serve(null, 503);
    show();
    expect(await screen.findByText("memory is not enabled on this server")).toBeInTheDocument();
  });
});

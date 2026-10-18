import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AsOfProvider } from "../asof";
import { AskView } from "./AskView";

const H = "a".repeat(64);
const QUESTION = "Was a risk flag raised after the Day 8 incident?";

const answer = (recalled: boolean) => ({
  tenant: "apex",
  kind: "SILENCE",
  answer: { exists: false, reasoning: "Searched 2 artifacts." },
  recalled,
  proof: { queries: [{ name: "absence", params: {}, sha256: H }] },
  trace: { stop_reason: recalled ? "recalled" : "planned", strategy_changes: [], llm_calls: recalled ? 0 : 1, prompt_tokens: 0, completion_tokens: 0, tools: [] },
});

function serve(recalled: boolean) {
  const calls: { url: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/actors")) return json({ actors: [{ name: "Alex", role: "engineering_mobile" }] });
      if (url.endsWith("/ask")) return json(answer(recalled));
      return json({
        session: "s",
        turns: [
          { n: 1, role: "user", content: QUESTION, seal: "" },
          { n: 2, role: "assistant", content: "No, it did not happen.", seal: "b".repeat(64) },
        ],
        facts: [],
        procedures: 1,
      });
    }),
  );
  return calls;
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AsOfProvider>
        <AskView />
      </AsOfProvider>
    </QueryClientProvider>,
  );
}

async function ask() {
  await userEvent.type(screen.getByLabelText("Your question"), QUESTION);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("AskView memory", () => {
  it("sends the tab's session with the question and then shows what the session remembers", async () => {
    const calls = serve(false);
    show();
    await ask();
    const region = await screen.findByRole("region", { name: "Memory" });
    expect(region).toHaveTextContent(QUESTION);
    const sent = calls.find((c) => c.url.endsWith("/ask"))?.body;
    expect(sent?.session).toMatch(/^[a-z0-9-]{8,64}$/);
    expect(sessionStorage.getItem("constellation.session")).toBe(sent?.session);
    expect(calls.find((c) => c.url.includes("/memory"))?.url).toContain(`session=${String(sent?.session)}`);
    expect(screen.queryByText(/Recalled from memory/)).not.toBeInTheDocument();
  });

  it("shows the recalled badge when the server answered from memory", async () => {
    serve(true);
    show();
    await ask();
    expect(await screen.findByText("Recalled from memory · proof re-verified")).toBeInTheDocument();
  });

  it("keeps working when the browser refuses storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const calls = serve(false);
    show();
    await ask();
    await screen.findByRole("region", { name: "Memory" });
    expect(calls.find((c) => c.url.endsWith("/ask"))?.body?.session).toMatch(/^[a-z0-9-]{8,64}$/);
    vi.restoreAllMocks();
  });

  it("does not read memory before anything has been asked", async () => {
    const calls = serve(false);
    show();
    await screen.findByText("Write a question, or pick one above.");
    expect(calls.some((c) => c.url.includes("/memory"))).toBe(false);
  });
});

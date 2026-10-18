import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomeView } from "./HomeView";

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HomeView />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("HomeView", () => {
  it("names the product, the promise and the way in", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    show();
    expect(screen.getByRole("heading", { level: 1, name: "Constellation" })).toBeInTheDocument();
    expect(screen.getByText("Every answer, with its proof.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", "#/ask");
  });

  it("shows the live graph's real counts, summed from what the server reports", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              summary: [
                { kind: "issue", state: "open", items: 1000 },
                { kind: "pr", state: "merged", items: 2500 },
              ],
              as_of: null,
              changes: [],
              repos: [],
              freshness: { newest: null, repositories: 74 },
              proof: { queries: [] },
            }),
            { status: 200 },
          ),
      ),
    );
    show();
    expect(await screen.findByText("3,500")).toBeInTheDocument();
    expect(screen.getByText("74")).toBeInTheDocument();
  });

  it("leaves the numbers out rather than inventing them when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    show();
    expect(await screen.findAllByText("·")).toHaveLength(2);
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveView } from "./LiveView";

const NOW_ROWS = [
  { kind: "issue", state: "open", items: 1063 },
  { kind: "issue", state: "closed", items: 2759 },
  { kind: "pr", state: "merged", items: 3518 },
];
const THEN_ROWS = [
  { kind: "issue", state: "open", items: 900 },
  { kind: "issue", state: "closed", items: 2000 },
];
const proof = (n: string) => ({ queries: [{ name: "live_summary", params: {}, sha256: n.repeat(64) }] });

function serve() {
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      urls.push(url);
      const at = url.includes("&at=");
      return new Response(
        JSON.stringify({
          summary: NOW_ROWS,
          as_of: at ? THEN_ROWS : null,
          changes: [{ item: "FalkorDB/core#7", title: "fix bounds", predicate: "state", old: "open", new: "merged", at: 1_770_000_000 }],
          repos: [{ repo: "FalkorDB/core", items: 321 }],
          freshness: { newest: "2026-10-18T05:00:00Z", repositories: 74 },
          proof: proof(at ? "b" : "a"),
        }),
        { status: 200 },
      );
    }),
  );
  return urls;
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LiveView />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveView", () => {
  it("shows the current counts, the latest change and how fresh the data is", async () => {
    serve();
    show();
    expect(await screen.findByText(/3,822/)).toBeInTheDocument();
    expect(screen.getByText("FalkorDB/core#7")).toBeInTheDocument();
    expect(screen.getByText("open → merged")).toBeInTheDocument();
    expect(screen.getByText(/74 repositories/)).toBeInTheDocument();
    expect(screen.getByText(/18 Oct 2026/)).toBeInTheDocument();
  });

  it("asks the server for the past when the slider moves, and shows both then and now", async () => {
    const urls = serve();
    show();
    await screen.findByText(/3,822/);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "8" } });
    await waitFor(() => expect(urls.some((u) => u.includes("&at="))).toBe(true));
    expect(await screen.findByText(/2,900/)).toBeInTheDocument();
    expect(screen.getByText("8 weeks ago")).toBeInTheDocument();
  });

  it("explains a failure instead of showing an empty page", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be loaded/i);
  });
});

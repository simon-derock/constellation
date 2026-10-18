import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphStage } from "./GraphStage";

vi.mock("react-force-graph-2d", () => ({ default: () => null }));

const VIEWS = [
  { id: "live-network", title: "Who works with whom", hint: "Collaboration", tenant: "falkordb" },
  { id: "live-repos", title: "Where people work", hint: "Repositories", tenant: "falkordb" },
];
const NODES = [
  { id: "Person:a", type: "Person", layer: "identity", label: "dawn-kingfisher", weight: 2, source_count: 2, confidence: 1, privacy_state: "public", scope: "graph" },
  { id: "Person:b", type: "Person", layer: "identity", label: "sharp-wolf", weight: 1, source_count: 1, confidence: 1, privacy_state: "public", scope: "graph" },
  { id: "Repo:r", type: "Repo", layer: "product", label: "FalkorDB/core", weight: 1, source_count: 1, confidence: 1, privacy_state: "public", scope: "graph" },
];
const EDGES = [
  { id: "e1", source: "Person:a", target: "Person:b", relationship_type: "COLLABORATES", confidence: 1, provenance_label: "FalkorDB" },
  { id: "e2", source: "Person:a", target: "Repo:r", relationship_type: "ACTIVE_IN", confidence: 1, provenance_label: "FalkorDB" },
];

function serve(failGraph = false) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/api/v1/graph/views")) return new Response(JSON.stringify({ views: VIEWS }), { status: 200 });
      if (url.includes("/api/v1/graph?")) {
        if (failGraph) return new Response("{}", { status: 503 });
        return new Response(
          JSON.stringify({ view: VIEWS[0], nodes: NODES, edges: EDGES, proof: { queries: [] } }),
          { status: 200 },
        );
      }
      return new Response("{}", { status: 404 });
    }),
  );
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GraphStage />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("GraphStage", () => {
  it("offers the server's views, starts on the first, and counts what the graph returned", async () => {
    serve();
    show();
    expect(await screen.findByText("3 nodes · 2 edges")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /who works with whom/i })).toBeInTheDocument();
  });

  it("a style brings its own theme only when that theme is light, so the graph stays on the page", async () => {
    serve();
    show();
    await screen.findByText("3 nodes · 2 edges");
    const theme = () => screen.getByRole("button", { name: /^theme/i });
    expect(theme()).toHaveTextContent("Bone");
    fireEvent.click(screen.getByRole("button", { name: /^style/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /chromatic web/i }));
    expect(theme()).toHaveTextContent("Bone");
    // the style menu stays open after a choice, so the next pick is made directly
    fireEvent.click(screen.getByRole("menuitem", { name: /^ivory ledger/i }));
    expect(theme()).toHaveTextContent("Ivory Ledger");
  });

  it("offers no dark theme, so a dark gamut cannot paint a black block into the page", async () => {
    serve();
    show();
    await screen.findByText("3 nodes · 2 edges");
    fireEvent.click(screen.getByRole("button", { name: /^theme/i }));
    expect(screen.queryByRole("menuitem", { name: /carbon/i })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /bone/i })).toBeInTheDocument();
  });

  it("selecting a view reads that view's graph again", async () => {
    serve();
    show();
    await screen.findByText("3 nodes · 2 edges");
    const fetched = vi.mocked(fetch);
    fireEvent.click(screen.getByRole("button", { name: /who works with whom/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /where people work/i }));
    await waitFor(() => expect(fetched.mock.calls.some(([u]) => String(u).includes("view=live-repos"))).toBe(true));
  });

  it("says plainly when the graph cannot be read, instead of drawing nothing", async () => {
    serve(true);
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be read/i);
  });
});

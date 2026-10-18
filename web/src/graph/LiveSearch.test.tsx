import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LiveSearch } from "./LiveSearch";

const HIT = { item: "o/a#1", title: "Vector index crashes on restart", repo: "o/a", via: ["vector", "text"] };
const PEOPLE = {
  central: [{ person: "dawn-kingfisher-f3", score: 0.0008 }],
  bridges: [{ person: "solar-swan-e2", score: 415 }],
  components: [{ size: 346, components: 1 }],
  proof: { queries: [] },
};

function serve(search: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.includes("/api/v1/live/search")) return new Response(JSON.stringify(search), { status: 200 });
      if (url.includes("/api/v1/live/people")) return new Response(JSON.stringify(PEOPLE), { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LiveSearch />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveSearch", () => {
  it("shows the people the graph ranks most connected and the bridges between others", async () => {
    serve({ hits: [], vector_used: true, proof: { queries: [] } });
    show();
    expect(await screen.findByText("dawn-kingfisher-f3")).toBeInTheDocument();
    expect(screen.getByText("solar-swan-e2")).toBeInTheDocument();
    expect(screen.getByText(/largest connected group holds 346/)).toBeInTheDocument();
  });

  it("returns hits with the way each one was found, in plain words", async () => {
    serve({ hits: [HIT], vector_used: true, proof: { queries: [] } });
    show();
    fireEvent.change(screen.getByLabelText(/ask the live graph/i), { target: { value: "crash" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Vector index crashes on restart")).toBeInTheDocument();
    expect(screen.getByText(/meaning \+ words/)).toBeInTheDocument();
  });

  it("says when only words were matched, because no embedder was available", async () => {
    serve({ hits: [{ ...HIT, via: ["text"] }], vector_used: false, proof: { queries: [] } });
    show();
    fireEvent.change(screen.getByLabelText(/ask the live graph/i), { target: { value: "crash" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Matched by words only")).toBeInTheDocument();
  });

  it("says plainly when nothing matches", async () => {
    serve({ hits: [], vector_used: true, proof: { queries: [] } });
    show();
    fireEvent.change(screen.getByLabelText(/ask the live graph/i), { target: { value: "zzzz" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.getByText("Nothing in the live graph matched.")).toBeInTheDocument());
  });

  it("does not search an empty box", async () => {
    serve({ hits: [], vector_used: true, proof: { queries: [] } });
    show();
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
  });
});

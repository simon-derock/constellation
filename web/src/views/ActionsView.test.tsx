import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionsView } from "./ActionsView";

const SUGGESTION = {
  kind: "file_issue",
  title: "Ownership gap: kubernetes-deploy had no owner from day 34 to day 42",
  body: "kubernetes-deploy had no recorded owner.",
  payload_hash: "a".repeat(64),
  evidence: [],
};
const PROPOSED = { id: "a1", kind: "file_issue", title: SUGGESTION.title, body: "", status: "proposed", approver: null, mode: null, result: null, evidence: [], created: "t", provenance: "rule", payload_hash: "b".repeat(64) };
const BY_AGENT = {
  ...PROPOSED,
  id: "g1",
  title: "Write the postmortem for the Day 8 incident",
  body: "No postmortem exists.\n\n- Evidence: absence result hash.",
  evidence: [
    { name: "absence", params: {}, sha256: "1".repeat(64) },
    { name: "find_events", params: {}, sha256: "2".repeat(64) },
  ],
  provenance: "agent",
};
const DRY = {
  ...PROPOSED,
  status: "executed",
  approver: "public demo (dry run)",
  mode: "dry-run",
  result: { dry_run: true, would_create: { repo: "o/r", title: "t", labels: ["agent-action"] } },
};

function serve(state: { actions: unknown[] }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
      if (url.includes("/actions/suggestions")) return json({ suggestions: [SUGGESTION] });
      if (url.endsWith("/approve")) {
        state.actions = [DRY];
        return json(DRY);
      }
      if (init?.method === "POST") {
        state.actions = [PROPOSED];
        return json(PROPOSED);
      }
      return json({ actions: state.actions });
    }),
  );
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ActionsView />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ActionsView", () => {
  it("walks a suggestion from proposal to a recorded dry run", async () => {
    serve({ actions: [] });
    show();
    expect(await screen.findByText(/Ownership gap: kubernetes-deploy/, { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText("No actions proposed yet")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Propose this action" }));
    await userEvent.click(await screen.findByRole("button", { name: "Approve as a dry run" }));

    expect(await screen.findByText(/Dry run: would file an issue in o\/r/)).toBeInTheDocument();
    expect(screen.getByText(/Approved by public demo \(dry run\)/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing was created/)).toBeInTheDocument();
  });

  it("offers a real approval only after an operator key is entered", async () => {
    serve({ actions: [PROPOSED] });
    show();
    await screen.findByRole("button", { name: "Approve as a dry run" });
    expect(screen.queryByRole("button", { name: "Approve and file the issue" })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Operator key"), "s3cret");
    expect(screen.getByRole("button", { name: "Approve and file the issue" })).toBeInTheDocument();
  });

  it("labels what the agent proposed and shows the evidence it cited, but not for a rule's action", async () => {
    serve({ actions: [BY_AGENT, PROPOSED] });
    show();
    expect(await screen.findByText("Proposed by the agent")).toBeInTheDocument();
    expect(screen.getAllByText("Proposed by the agent")).toHaveLength(1);
    expect(screen.getByText(/No postmortem exists/)).toBeInTheDocument();
    const cited = screen.getByLabelText("Evidence the agent cited");
    expect(cited).toHaveTextContent("absence");
    expect(cited).toHaveTextContent(`${"1".repeat(12)}…`);
    expect(cited).toHaveTextContent(`${"2".repeat(12)}…`);
    expect(screen.getByTitle("2".repeat(64))).toBeInTheDocument();
  });

  it("holds an agent proposal for the same approval as any other action", async () => {
    serve({ actions: [BY_AGENT] });
    show();
    expect(await screen.findByRole("button", { name: "Approve as a dry run" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve and file the issue" })).not.toBeInTheDocument();
    expect(screen.getByText("proposed")).toBeInTheDocument();
  });

  it("says so when the graph suggests nothing", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(url.includes("suggestions") ? { suggestions: [] } : { actions: [] }), { status: 200 })));
    show();
    expect(await screen.findByText("The graph shows nothing that needs follow-up.")).toBeInTheDocument();
  });
});

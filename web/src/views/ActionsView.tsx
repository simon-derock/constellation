import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { actionList, ApiError, approveAction, proposeAction, suggestions, type ActionRecord } from "../lib/api";

const TENANT = "apex";

function outcome(action: ActionRecord): string {
  const result = action.result ?? {};
  if (action.status === "failed") return `Failed: ${String(result.error ?? "no reason recorded")}.`;
  if (action.status !== "executed") return "";
  if (result.dry_run === true) {
    const would = result.would_create as { repo?: string; labels?: string[] } | undefined;
    return `Dry run: would file an issue in ${would?.repo ?? "the repository"} labelled ${(would?.labels ?? []).join(", ")}. Nothing was created.`;
  }
  return `Issue filed: ${String(result.url ?? "")}`;
}

const message = (error: unknown) => (error instanceof ApiError ? error.message : "Something went wrong. Try again.");

export function ActionsView() {
  const client = useQueryClient();
  const [operatorKey, setOperatorKey] = useState("");
  const found = useQuery({ queryKey: ["suggestions", TENANT], queryFn: () => suggestions(TENANT) });
  const recorded = useQuery({ queryKey: ["actions"], queryFn: actionList });
  const refresh = () => client.invalidateQueries({ queryKey: ["actions"] });

  const propose = useMutation({ mutationFn: (hash: string) => proposeAction(TENANT, hash), onSuccess: refresh });
  const approve = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: "dry-run" | "real" }) => approveAction(id, mode, operatorKey),
    onSuccess: refresh,
  });
  const proposedHashes = new Set(recorded.data?.actions.map((a) => a.title));

  return (
    <div className="page" data-ghost="Act">
      <h1>What should happen next</h1>
      <p className="lede">Nothing runs until someone approves it, and every decision records who made it.</p>

      <h2>Suggested</h2>
      {found.isPending && <p className="hint">Reading the graph…</p>}
      {found.error && (
        <p className="result bad" role="alert">
          Suggestions could not be loaded. {message(found.error)}
        </p>
      )}
      {found.data?.suggestions.length === 0 && <p className="hint">The graph shows nothing that needs follow-up.</p>}
      <ul className="actions">
        {found.data?.suggestions.map((s) => (
          <li key={s.payload_hash}>
            <h3>{s.title}</h3>
            <pre className="body">{s.body}</pre>
            <button
              type="button"
              className="primary"
              disabled={propose.isPending || proposedHashes.has(s.title)}
              onClick={() => propose.mutate(s.payload_hash)}
            >
              {proposedHashes.has(s.title) ? "Proposed" : "Propose this action"}
            </button>
          </li>
        ))}
      </ul>
      {propose.error && (
        <p className="result bad" role="alert">
          {message(propose.error)}
        </p>
      )}

      <h2>Decisions</h2>
      {recorded.data?.actions.length === 0 && (
        <div className="empty">
          <h2>No actions proposed yet</h2>
          <p>Propose a suggestion above and it appears here, waiting for approval.</p>
        </div>
      )}
      <ul className="actions">
        {recorded.data?.actions.map((a) => (
          <li key={a.id}>
            <h3>{a.title}</h3>
            <p className="status">
              <span className={`pill ${a.status}`}>{a.status}</span>
              {a.approver && <span className="hint"> Approved by {a.approver}.</span>}
            </p>
            {outcome(a) && <p className="detail">{outcome(a)}</p>}
            {a.status === "proposed" && (
              <button type="button" className="replay" disabled={approve.isPending} onClick={() => approve.mutate({ id: a.id, mode: "dry-run" })}>
                Approve as a dry run
              </button>
            )}
            {a.status === "proposed" && operatorKey && (
              <button type="button" className="link" onClick={() => approve.mutate({ id: a.id, mode: "real" })}>
                Approve and file the issue
              </button>
            )}
          </li>
        ))}
      </ul>
      {approve.error && (
        <p className="result bad" role="alert">
          {message(approve.error)}
        </p>
      )}

      <details className="operator">
        <summary>Operator</summary>
        <label htmlFor="operator-key">Operator key</label>
        <input
          id="operator-key"
          type="password"
          autoComplete="off"
          value={operatorKey}
          onChange={(e) => setOperatorKey(e.target.value)}
        />
        <p className="hint">Kept in this tab only. With it, an approval files a real issue; without it, approvals are dry runs.</p>
      </details>
    </div>
  );
}

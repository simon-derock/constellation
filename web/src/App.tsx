import { useEffect, useState } from "react";
import { AsOfProvider } from "./asof";
import { ActionsView } from "./views/ActionsView";
import { AskView } from "./views/AskView";
import { LiveView } from "./views/LiveView";
import { OwnershipView } from "./views/OwnershipView";
import { ScoreboardView } from "./views/ScoreboardView";

const VIEWS = [
  { id: "ask", label: "Ask", view: <AskView /> },
  { id: "ownership", label: "Ownership", view: <OwnershipView /> },
  { id: "live", label: "Live", view: <LiveView /> },
  { id: "act", label: "Act", view: <ActionsView /> },
  { id: "scoreboard", label: "Scoreboard", view: <ScoreboardView /> },
] as const;

type ViewId = (typeof VIEWS)[number]["id"];

function current(): ViewId {
  const id = window.location.hash.replace(/^#\/?/, "");
  return VIEWS.find((v) => v.id === id)?.id ?? "ask";
}

export function App() {
  const [id, setId] = useState<ViewId>(current);
  useEffect(() => {
    const onChange = () => setId(current());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const active = VIEWS.find((v) => v.id === id)!;
  return (
    <AsOfProvider>
      <header className="top">
        <a href="#/ask" className="mark" aria-label="Constellation home">
          <svg viewBox="0 0 16 16" width="22" height="22" aria-hidden="true">
            <rect x="1" y="1" width="6" height="6" fill="var(--verified)" />
            <rect x="9" y="9" width="6" height="6" fill="var(--verified)" />
            <rect x="9" y="1" width="6" height="6" fill="none" stroke="var(--ink)" />
            <rect x="1" y="9" width="6" height="6" fill="none" stroke="var(--ink)" />
          </svg>
          Constellation
        </a>
        <nav aria-label="Sections">
          {VIEWS.map((v) => (
            <a key={v.id} href={`#/${v.id}`} aria-current={v.id === id ? "page" : undefined}>
              {v.label}
            </a>
          ))}
        </nav>
      </header>
      <main>{active.view}</main>
    </AsOfProvider>
  );
}

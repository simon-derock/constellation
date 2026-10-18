import { useEffect, useState } from "react";
import { AsOfProvider } from "./asof";
import { ActionsView } from "./views/ActionsView";
import { AskView } from "./views/AskView";
import { HomeView } from "./views/HomeView";
import { LiveView } from "./views/LiveView";
import { OwnershipView } from "./views/OwnershipView";
import { ScoreboardView } from "./views/ScoreboardView";

const VIEWS = [
  { id: "home", label: "Home", nav: false, view: <HomeView /> },
  { id: "ask", label: "Ask", nav: true, view: <AskView /> },
  { id: "ownership", label: "Ownership", nav: true, view: <OwnershipView /> },
  { id: "live", label: "Live", nav: true, view: <LiveView /> },
  { id: "act", label: "Act", nav: true, view: <ActionsView /> },
  { id: "scoreboard", label: "Scoreboard", nav: true, view: <ScoreboardView /> },
] as const;

type ViewId = (typeof VIEWS)[number]["id"];

function current(): ViewId {
  const id = window.location.hash.replace(/^#\/?/, "");
  return VIEWS.find((v) => v.id === id)?.id ?? "home";
}

export function App() {
  const [id, setId] = useState<ViewId>(current);
  useEffect(() => {
    const onChange = () => {
      setId(current());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const active = VIEWS.find((v) => v.id === id)!;
  return (
    <AsOfProvider>
      <header className="top">
        <a href="#/home" className="mark" aria-label="Constellation home">
          Constellation
        </a>
        <nav aria-label="Sections">
          {VIEWS.filter((v) => v.nav).map((v) => (
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

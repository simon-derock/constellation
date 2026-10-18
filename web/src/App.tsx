import { AsOfProvider } from "./asof";
import { ActionsView } from "./views/ActionsView";
import { AskView } from "./views/AskView";
import { HomeView } from "./views/HomeView";
import { LiveView } from "./views/LiveView";
import { OwnershipView } from "./views/OwnershipView";
import { ScoreboardView } from "./views/ScoreboardView";

const REPO = "https://github.com/simon-derock/constellation";

// every section lives on one scrolling page; the menu jumps to a section rather than opening another page
const SECTIONS = [
  { id: "ask", label: "Ask", view: <AskView /> },
  { id: "ownership", label: "Ownership", view: <OwnershipView /> },
  { id: "live", label: "Live", view: <LiveView /> },
  { id: "act", label: "Act", view: <ActionsView /> },
  { id: "scoreboard", label: "Scoreboard", view: <ScoreboardView /> },
] as const;

export function App() {
  return (
    <AsOfProvider>
      <header className="top">
        <div className="brand">
          <a href={REPO} className="gh-icon" target="_blank" rel="noreferrer" aria-label="Constellation on GitHub">
            <svg viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
              <path d="M12 .7a11.3 11.3 0 0 0-3.57 22c.57.1.78-.25.78-.55v-2.1c-3.18.69-3.85-1.34-3.85-1.34-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.02 1.75 2.68 1.24 3.34.95.1-.74.4-1.24.73-1.53-2.54-.29-5.21-1.27-5.21-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.45.11-3.03 0 0 .96-.31 3.13 1.17A10.9 10.9 0 0 1 12 6c.97 0 1.95.13 2.86.38 2.17-1.48 3.13-1.17 3.13-1.17.62 1.58.23 2.74.11 3.03.73.8 1.18 1.82 1.18 3.07 0 4.4-2.68 5.36-5.23 5.64.41.36.78 1.07.78 2.16v3.2c0 .3.2.66.79.55A11.3 11.3 0 0 0 12 .7Z" fill="currentColor" />
            </svg>
          </a>
          <a href="#top" className="mark" aria-label="Constellation home">
            Constellation
          </a>
        </div>
        <nav aria-label="Sections">
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#${s.id}`}>
              {s.label}
            </a>
          ))}
          <a href={`${REPO}/tree/main/docs`} className="docs-btn" target="_blank" rel="noreferrer">
            Docs
          </a>
        </nav>
      </header>
      <p className="efficiency">50,000 nodes in 73 MB on one FalkorDB engine, and every answer is a replayable Cypher proof.</p>
      <main>
        <section id="top" className="scroll-home">
          <HomeView />
        </section>
        {SECTIONS.map((s) => (
          <section key={s.id} id={s.id} className="scroll-section" aria-label={s.label}>
            {s.view}
          </section>
        ))}
      </main>
    </AsOfProvider>
  );
}

import { useQuery } from "@tanstack/react-query";
import { GraphStage } from "../graph/GraphStage";
import { LiveSearch } from "../graph/LiveSearch";
import { live } from "../lib/api";

const PILLARS = [
  { n: "I", t: "Proof", d: "Every answer ships with the exact queries behind it, and a seal you can replay." },
  { n: "II", t: "Time", d: "What was true on any day, kept alongside what is true now. Nothing is overwritten." },
  { n: "III", t: "Restraint", d: "Agents propose and people approve. The graph records who decided." },
];

const count = (rows: { items: number }[]) => rows.reduce((sum, r) => sum + r.items, 0);

// the reference site's page, section for section: hero, epigraph, three pillars, three figures, a closing call, colophon
export function HomeView() {
  // the figures are read from the live graph, never typed in; with no server they are left as a dot
  const tenant = useQuery({ queryKey: ["live", "falkordb", undefined], queryFn: () => live("falkordb"), retry: false });
  const items = tenant.data ? count(tenant.data.summary) : null;
  const repos = tenant.data?.freshness.repositories ?? null;
  return (
    <div className="home">
      <header className="hero">
        <div className="hero-copy">
          <p className="kicker rise">Introducing</p>
          <h1 className="rise" style={{ animationDelay: ".15s" }}>
            Constellation
          </h1>
          <p className="tagline rise" style={{ animationDelay: ".3s" }}>
            Every answer, with its proof.
          </p>

        </div>

        <aside className="corner corner-tl" aria-label="Graph Hacks">
          <p className="corner-head">Graph Hacks: Context for AI Agents</p>
          <p>WeMakeDevs × FalkorDB</p>
        </aside>
      </header>

      <div className="home-graph">
        <GraphStage />
      </div>

      <div className="home-body">
        <LiveSearch />

        <div className="eyebrow">
          <span>Open source</span>
        </div>

        <section className="quote">
          <p>“A company brain that remembers what was true, and shows its work.”</p>
        </section>

        <section className="pillars">
          {PILLARS.map((p) => (
            <div key={p.n}>
              <div className="numeral">{p.n}</div>
              <h3>{p.t}</h3>
              <div className="tick" />
              <p>{p.d}</p>
            </div>
          ))}
        </section>

        <section className="stats" aria-label="The live graph">
          <div>
            <div className="big">{items === null ? "·" : items.toLocaleString()}</div>
            <div className="cap">items tracked</div>
          </div>
          <div>
            <div className="big">{repos === null ? "·" : repos}</div>
            <div className="cap">repositories</div>
          </div>
          <div>
            <div className="big">MIT</div>
            <div className="cap">licence</div>
          </div>
        </section>

        <section className="begin">
          <p className="kicker">Begin</p>
          <h2>Ask, then check.</h2>
          <p className="soft">Pick a question, read the answer, and replay its proof against the graph.</p>
          <a className="enter" href="#ask">
            Ask
          </a>
        </section>

        <footer className="colophon">
          <p>Constellation · MMXXVI</p>
          <p className="signature">— Philip Simon Derock</p>
        </footer>
      </div>
    </div>
  );
}

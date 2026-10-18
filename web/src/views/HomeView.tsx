import { useQuery } from "@tanstack/react-query";
import { live } from "../lib/api";

const PILLARS = [
  { n: "I", t: "Proof", d: "Every answer ships with the exact queries behind it, and a seal you can replay." },
  { n: "II", t: "Time", d: "What was true on any day, kept alongside what is true now. Nothing is overwritten." },
  { n: "III", t: "Restraint", d: "Agents propose and people approve. The graph records who decided." },
];

const count = (rows: { items: number }[]) => rows.reduce((sum, r) => sum + r.items, 0);

export function HomeView() {
  // the numbers are read from the live graph, never typed in; with no server they are simply left out
  const tenant = useQuery({ queryKey: ["live", "falkordb", undefined], queryFn: () => live("falkordb"), retry: false });
  const items = tenant.data ? count(tenant.data.summary) : null;
  const repos = tenant.data?.freshness.repositories ?? null;
  return (
    <div className="home">
      <section className="hero">
        <div className="hero-copy">
          <p className="label rise">A company brain</p>
          <h1 className="rise" style={{ animationDelay: ".15s" }}>
            Constellation
          </h1>
          <p className="tagline rise" style={{ animationDelay: ".3s" }}>
            Every answer, with its proof.
          </p>
        </div>
      </section>

      <p className="label center faint">Open source</p>

      <section className="quote">
        <p>“Ask anything. Check everything. A graph that remembers what was true, and shows its work.”</p>
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

      <section className="figures-row" aria-label="The live graph">
        <div>
          <div className="big">{items === null ? "·" : items.toLocaleString()}</div>
          <div className="label small">items tracked</div>
        </div>
        <div>
          <div className="big">{repos === null ? "·" : repos}</div>
          <div className="label small">repositories</div>
        </div>
        <div>
          <div className="big">MIT</div>
          <div className="label small">licence</div>
        </div>
      </section>

      <section className="begin">
        <p className="label">Begin</p>
        <h2>Ask, then check.</h2>
        <p className="body-soft">Pick a question, read the answer, and replay its proof against the graph.</p>
        <a className="primary" href="#/ask">
          Ask
        </a>
      </section>

      <footer className="colophon">Constellation · MMXXVI</footer>
    </div>
  );
}

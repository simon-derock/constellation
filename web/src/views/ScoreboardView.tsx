import { Figures } from "../components/Figures";
import { useQuery } from "@tanstack/react-query";
import { scoreboard } from "../lib/api";

const pct = (value: number) => value.toFixed(3);

export function ScoreboardView() {
  const runs = useQuery({ queryKey: ["scoreboard"], queryFn: scoreboard });
  return (
    <div className="page">
      <Figures size="page" />
      <h1>Benchmark runs</h1>
      <p className="lede">Scored by the benchmark's own code. A leak cannot be bought back with a good answer.</p>
      {runs.isPending && <p className="hint">Loading runs…</p>}
      {runs.error && (
        <p className="result bad" role="alert">
          The runs could not be loaded. Try again in a moment.
        </p>
      )}
      {runs.data && runs.data.runs.length === 0 && (
        <div className="empty">
          <p>A run appears here once it has finished.</p>
        </div>
      )}
      {runs.data?.runs.map((run, i) => (
        <section key={`${run.model}-${i}`} className="run">
          <h2>{run.model}</h2>
          <p className="hint">{run.questions} questions</p>
          <table>
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Score</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Violation-adjusted combined</th>
                <td>{pct(run.violation_adjusted_combined_score)}</td>
              </tr>
              <tr>
                <th scope="row">Combined</th>
                <td>{pct(run.combined_score)}</td>
              </tr>
              <tr>
                <th scope="row">Answer accuracy</th>
                <td>{pct(run.accuracy)}</td>
              </tr>
              <tr>
                <th scope="row">Violation rate</th>
                <td>{pct(run.violation_rate)}</td>
              </tr>
              {Object.entries(run.by_track).map(([track, score]) => (
                <tr key={track}>
                  <th scope="row">{track.charAt(0) + track.slice(1).toLowerCase()}</th>
                  <td>{pct(score)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

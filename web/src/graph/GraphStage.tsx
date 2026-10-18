import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type WheelEvent } from "react";
import { ProofPanel } from "../components/ProofPanel";
import { graphView, graphViews } from "../lib/api";
import { GraphSurface } from "./GraphSurface";
import { THEMES } from "./themes";
import type { GraphNode, Palette, VizProfile } from "./types";
import { VIZ_PROFILES } from "./viz";

interface Option {
  id: string;
  name: string;
  hint?: string;
  swatches?: string[];
}

// the page's own paper, so the canvas and the page are one surface; only light themes are offered, because their ink
// reads on paper and a dark gamut would print a black block into the warm page
const PAGE_PAPER = "#f1f0ec";

function luminance(hex: string): number {
  const v = hex.replace("#", "");
  const full = v.length === 3 ? v.split("").map((c) => c + c).join("") : v;
  const n = parseInt(full, 16);
  return (((n >> 16) & 255) * 0.299 + ((n >> 8) & 255) * 0.587 + (n & 255) * 0.114) / 255;
}

const LIGHT_THEMES = THEMES.filter((t) => luminance(t.palette.paper) >= 0.8);

// a flat instrument-panel menu: one plate that opens a list, and optionally steps through options on wheel
function Menu({
  tag,
  value,
  options,
  onChange,
  align,
  keepOpen = false,
  wheel = false,
}: {
  tag: string;
  value: string;
  options: Option[];
  onChange: (id: string) => void;
  align: "start" | "end";
  keepOpen?: boolean;
  wheel?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const active = options.find((o) => o.id === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  const step = (event: WheelEvent<HTMLButtonElement>) => {
    if (!wheel || options.length < 2) return;
    event.preventDefault();
    const current = Math.max(0, options.findIndex((o) => o.id === value));
    const next = (current + (event.deltaY > 0 ? 1 : -1) + options.length) % options.length;
    onChange(options[next]!.id);
  };

  return (
    <div ref={box} className="gs-menu">
      <button
        type="button"
        className="gs-plate gs-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onWheel={step}
      >
        <span className="gs-tag">{tag}</span>
        <span className="gs-value">{active?.name ?? "—"}</span>
        {active?.swatches && (
          <span className="gs-swatches" aria-hidden="true">
            {active.swatches.slice(0, 4).map((c, i) => (
              <span key={i} style={{ background: c }} />
            ))}
          </span>
        )}
      </button>
      {open && (
        <div role="menu" className={`gs-popover gs-popover-${align}`}>
          {options.map((o) => (
            <button
              key={o.id}
              type="button"
              role="menuitem"
              aria-current={o.id === value ? "true" : undefined}
              onClick={() => {
                onChange(o.id);
                if (!keepOpen) setOpen(false);
              }}
            >
              <span className="gs-mark">{o.id === value ? "▪" : ""}</span>
              <span className="gs-option">
                <span className="gs-option-name">{o.name}</span>
                {o.hint && <span className="gs-option-hint">{o.hint}</span>}
              </span>
              {o.swatches && (
                <span className="gs-swatches" aria-hidden="true">
                  {o.swatches.slice(0, 6).map((c, i) => (
                    <span key={i} style={{ background: c }} />
                  ))}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// the Lunarbit console, on Constellation's page: a view of the graph, a drawing style that brings its own theme, and
// the colours of that theme; the nodes come from the graph's own queries and the proof is shown under the canvas
export function GraphStage() {
  const views = useQuery({ queryKey: ["graph-views"], queryFn: graphViews, retry: false });
  const [chosen, setChosen] = useState<string | null>(null);
  const [vizId, setVizId] = useState("architectural-constellation");
  const [themeId, setThemeId] = useState(LIGHT_THEMES[0]!.id);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const viewList = views.data?.views ?? [];
  const active = viewList.find((v) => v.id === chosen) ?? viewList[0];
  const graph = useQuery({
    queryKey: ["graph", active?.id],
    queryFn: () => graphView(active!.id),
    enabled: Boolean(active),
    retry: false,
  });

  const theme = LIGHT_THEMES.find((t) => t.id === themeId) ?? LIGHT_THEMES[0]!;
  const palette: Palette = { ...theme.palette, paper: PAGE_PAPER };
  const viz: VizProfile = VIZ_PROFILES.find((v) => v.id === vizId) ?? VIZ_PROFILES[0]!;
  const nodes = useMemo(() => graph.data?.nodes ?? [], [graph.data]);
  const edges = useMemo(() => graph.data?.edges ?? [], [graph.data]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const selected: GraphNode | null = (selectedId && byId.get(selectedId)) || null;
  const relations = useMemo(() => {
    if (!selected) return [];
    return edges
      .filter((e) => e.source === selected.id || e.target === selected.id)
      .map((e) => {
        const outgoing = e.source === selected.id;
        const other = byId.get(outgoing ? e.target : e.source);
        return { id: e.id, rel: e.relationship_type, other: other?.label ?? "", outgoing };
      });
  }, [edges, byId, selected]);

  // a style brings its own theme when that theme is one of the light ones; otherwise the page keeps its theme
  const chooseStyle = (id: string) => {
    setVizId(id);
    const next = VIZ_PROFILES.find((v) => v.id === id);
    if (next && LIGHT_THEMES.some((t) => t.id === next.preferredTheme)) setThemeId(next.preferredTheme);
  };

  const failed = views.isError || graph.isError;

  return (
    <section className="graph-stage" aria-label="The live graph">
      <header className="gs-bar">
        <Menu
          tag="view"
          value={active?.id ?? ""}
          align="start"
          wheel
          onChange={setChosen}
          options={viewList.map((v) => ({ id: v.id, name: v.title, hint: v.hint }))}
        />
        <div className="gs-bar-right">
          <Menu
            tag="style"
            value={vizId}
            align="end"
            keepOpen
            wheel
            onChange={chooseStyle}
            options={VIZ_PROFILES.map((v) => ({ id: v.id, name: v.name, hint: v.hint }))}
          />
          <Menu
            tag="theme"
            value={themeId}
            align="end"
            keepOpen
            wheel
            onChange={setThemeId}
            options={LIGHT_THEMES.map((t) => ({ id: t.id, name: t.name, hint: t.hint, swatches: Object.values(t.palette.layers) }))}
          />
        </div>
      </header>

      <div className="gs-canvas">
        {views.isSuccess && viewList.length === 0 && <p className="gs-status">No views are published yet.</p>}
        {(views.isPending || (active && graph.isPending)) && !failed && <p className="gs-status">Reading the graph…</p>}
        {failed && (
          <p className="gs-status" role="alert">
            The graph could not be read. Check that the server is running and try again.
          </p>
        )}
        {graph.data && (
          <GraphSurface
            nodes={nodes}
            edges={edges}
            palette={palette}
            viz={viz}
            selectedId={selectedId}
            onSelect={(node) => setSelectedId(node?.id ?? null)}
            onLinkSelect={() => undefined}
          />
        )}
        {selected && (
          <aside className="gs-plate gs-inspector" aria-label="Selected node">
            <div className="gs-inspector-head">
              <span className="gs-tag">{selected.type}</span>
              <button type="button" className="gs-close" onClick={() => setSelectedId(null)}>
                close
              </button>
            </div>
            <div className="gs-node">
              <span className="gs-swatch" style={{ background: palette.layers[selected.layer] }} />
              <span className="gs-node-label">{selected.label}</span>
            </div>
            <dl className="gs-facts">
              <dt>layer</dt>
              <dd>{selected.layer}</dd>
              <dt>weight</dt>
              <dd>{selected.weight}</dd>
            </dl>
            <ul className="gs-relations" aria-label="Relationships">
              {relations.map((r) => (
                <li key={r.id}>
                  <span className="gs-tag">{r.rel.toLowerCase().replaceAll("_", " ")}</span>
                  <span className="gs-other">
                    {r.outgoing ? "→" : "←"} {r.other}
                  </span>
                </li>
              ))}
            </ul>
          </aside>
        )}
      </div>

      <footer className="gs-foot">
        <span className="gs-tag">
          {nodes.length} nodes · {edges.length} edges
        </span>
        {active && <span className="gs-hint">{active.hint}</span>}
      </footer>

      {graph.data && <ProofPanel tenant={graph.data.view.tenant} queries={graph.data.proof.queries} />}
    </section>
  );
}

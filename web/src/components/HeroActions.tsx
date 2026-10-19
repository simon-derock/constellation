import { useState } from "react";

// the MCP server is mounted beside the API; in development Vite proxies /mcp, so the page's own origin always works.
// No trailing slash: the Vercel rewrite matches /mcp, and the API serves it without a redirect from there
export function mcpUrl(): string {
  const base = import.meta.env.VITE_API_URL || window.location.origin;
  return `${base.replace(/\/$/, "")}/mcp`;
}

const CLIENTS = [
  { id: "claude", label: "Claude Code", snippet: (url: string) => `claude mcp add --transport http constellation ${url}` },
  { id: "json", label: "Any client", snippet: (url: string) => JSON.stringify({ mcpServers: { constellation: { url } } }, null, 2) },
] as const;

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      window.setTimeout(() => setDone(false), 1600);
    } catch {
      // no clipboard (insecure origin, denied permission): the text stays selectable on screen
      setDone(false);
    }
  };
  return (
    <button type="button" className="mcp-copy" onClick={() => void copy()}>
      {done ? "Copied" : "Copy"}
    </button>
  );
}

// the two ways in: ask the graph here, or connect an agent to the same graph over MCP
export function HeroActions() {
  const [open, setOpen] = useState(false);
  const [client, setClient] = useState<(typeof CLIENTS)[number]["id"]>("claude");
  const url = mcpUrl();
  const snippet = CLIENTS.find((c) => c.id === client)!.snippet(url);
  return (
    <div className="hero-actions rise" style={{ animationDelay: ".4s" }}>
      <div className="hero-buttons">
        <a className="cta cta-primary" href="#ask">
          Ask the graph <span aria-hidden="true">→</span>
        </a>
        <button type="button" className="cta cta-ghost" aria-expanded={open} aria-controls="mcp-panel" onClick={() => setOpen((o) => !o)}>
          <span className="cta-mark" aria-hidden="true" />
          Connect over MCP
        </button>
      </div>
      {open && (
        <div id="mcp-panel" className="mcp-panel" role="region" aria-label="Connect over MCP">
          <p className="mcp-label">MCP · streamable HTTP · every tool returns its proof</p>
          <div className="mcp-url">
            <code>{url}</code>
            <Copy text={url} />
          </div>
          <div className="mcp-tabs" role="tablist" aria-label="Client">
            {CLIENTS.map((c) => (
              <button key={c.id} type="button" role="tab" aria-selected={c.id === client} className={c.id === client ? "on" : ""} onClick={() => setClient(c.id)}>
                {c.label}
              </button>
            ))}
          </div>
          <div className="mcp-snippet">
            <pre>{snippet}</pre>
            <Copy text={snippet} />
          </div>
        </div>
      )}
    </div>
  );
}

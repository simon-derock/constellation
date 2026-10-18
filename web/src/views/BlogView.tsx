// the best-blog entry for Graph Hacks: where each agent decision comes from the graph, track by track, and what broke
const DECISIONS: { ask: string; tool: string; how: string }[] = [
  { ask: "Who owned this on day D?", tool: "owner_as_of", how: "an interval on the OWNS edge: o.from <= $day AND (o.to IS NULL OR $day < o.to)" },
  { ask: "Who could have known about this event?", tool: "could_have_known", how: "the person's visibility cone on that day, intersected with who took part in the event" },
  { ask: "Did the expected follow-up ever happen?", tool: "absence", how: "(Event)-[:EXPECTS]->(Expectation) then OPTIONAL MATCH (x)-[:MET_BY]->(r): silence is a result" },
  { ask: "Who is central, and who bridges others?", tool: "live_central_people, live_bridge_people", how: "algo.pageRank and algo.betweenness over COLLABORATES, inside the engine" },
  { ask: "How are two people connected?", tool: "live_path", how: "shortestPath((a)-[:COLLABORATES*..8]->(b))" },
  { ask: "Which issues match this phrase?", tool: "live_search_vector + live_search_text", how: "db.idx.vector.queryNodes (HNSW) and db.idx.fulltext.queryNodes, fused by rank" },
  { ask: "What was open eight weeks ago?", tool: "live_state_as_of", how: "Claim nodes with valid_from and valid_to, linked by SUPERSEDES" },
];

export function BlogView() {
  return (
    <article className="blog">
      <p className="blog-kicker">Graph Hacks · Constellation</p>
      <h1>Every answer, with its proof, on one FalkorDB graph</h1>
      <p className="blog-lede">
        Ask an AI agent who knew about an outage and you get a confident paragraph with nothing to check it against.
        Constellation answers from a FalkorDB graph and hands back the exact queries that produced the answer, each with
        a hash of its result. Anyone can replay them. This post is about where the agent's decisions come from in the
        graph, across the three tracks, and about what broke on the way.
      </p>

      <img className="blog-figure" src="/graph-live.png" alt="The live graph: people in FalkorDB's GitHub organisation, linked by shared repositories" />
      <p className="blog-caption">The live tenant: FalkorDB's own public GitHub organisation, drawn from the graph. Big diamonds are PageRank leaders.</p>

      <h2>The graph</h2>
      <p>
        One FalkorDB engine holds three families of graph, about 50,000 nodes in 74 MB with the indexes included. A
        simulated company (<code>brain:apex</code>) has people, events, artifacts, roles and ownership as intervals on
        edges, causal links between events, and expectations that later events either meet or do not. FalkorDB's own
        GitHub organisation (<code>brain:falkordb</code>) has 8,135 issues and pull requests as <code>Item</code> nodes,
        each state it held as a <code>Claim</code> with a valid-from and valid-to, claims linked by{" "}
        <code>SUPERSEDES</code>, and 347 people as pseudonyms with a <code>COLLABORATES</code> projection. Every agent
        also gets a memory graph of its own.
      </p>

      <h2>Where the agent's decisions come from</h2>
      <p>
        The model never writes Cypher. It picks the name of a reviewed query and its arguments, and the verdict is read
        from the rows FalkorDB returns.
      </p>
      <div className="blog-table" role="table" aria-label="Agent decisions and the graph features behind them">
        {DECISIONS.map((d) => (
          <div key={d.tool} className="blog-row" role="row">
            <p className="blog-q" role="cell">{d.ask}</p>
            <p role="cell"><code>{d.tool}</code></p>
            <p className="blog-how" role="cell">{d.how}</p>
          </div>
        ))}
      </div>

      <h2>Track 03 · Company Brain: proofs and time</h2>
      <p>
        An answer is a list of named queries, their parameters and the SHA-256 of what each returned. Replay re-runs
        them through <code>GRAPH.RO_QUERY</code>, so the engine itself refuses writes, and any change shows up on the
        exact query that changed. Because facts are claims with intervals, "what was true on day D" is a query and
        nothing is overwritten. "Who could have known" is answered from one person's point of view: on the benchmark's
        30 such questions, none of 62 lookups reached past what the person could see.
      </p>

      <h2>Track 01 · Agents that act</h2>
      <p>
        The agent's tools are those queries and FalkorDB's algorithms, also served over MCP. After an answer it may
        propose one follow-up action, for example filing the missing postmortem it just found was never written. The
        server only accepts the proposal if every piece of evidence is a proof from a query the agent ran in that same
        answer, so it cannot cite something it did not read. A person approves it: a dry run by default, a real GitHub
        issue when an operator approves with a token.
      </p>

      <h2>Track 02 · Memory and coordination</h2>
      <p>
        Each agent's memory is its own graph, cloned from a template with <code>GRAPH.COPY</code>. It holds session
        turns, episodes, and facts that are only learned when two or more episodes agree and none disagree. Ask the same
        question again and the stored queries are replayed against the current graph first; only if every hash still
        matches is the answer recalled, with zero model calls. Writes are compare-and-set, so two agents can never lose
        each other's update, and a hand-off is claimed by exactly one agent. Other agents reach all of it over MCP.
      </p>

      <h2>What broke</h2>
      <ul>
        <li>
          <strong>Betweenness ate the machine.</strong> <code>algo.betweenness</code> memory grows with its sample size.
          A sample of 100,000 tried to allocate about 27 GB and was killed in a 3 GB container. A fixed sample just above
          the node count is exact at this size and repeatable.
        </li>
        <li>
          <strong>A restored graph needs its own name.</strong> Restoring a dump under a different key failed, so the
          snapshot copier keeps the graph's name.
        </li>
        <li>
          <strong>Free model tiers are small.</strong> One free provider allows 8,000 tokens a minute, and a single
          "what if" question used about 6,400. The answer was caching what can be proven: a repeated question is
          recalled after its proof replays, and the app moves to the next provider when one runs out.
        </li>
        <li>
          <strong>Retrieval ideas lost.</strong> On 511,962 documents, keyword search put a right document in the top
          ten 74.5% of the time. Small dense models scored lower, feedback expansion hurt, and a query rewrite by a
          small model hurt. A reranker over the fused candidates lifted it to 88.1%. I had set 99% as the target and did
          not reach it.
        </li>
      </ul>

      <h2>What is not built</h2>
      <p>
        There is no voice or meeting data, no model-written Cypher, and no authentication on the MCP endpoint, so its
        memory tools should sit behind a key before the endpoint is public. A deploy image exists but I have not verified
        it end to end, so the app runs locally from the README's steps.
      </p>

      <h2>Try it</h2>
      <p>
        The source, the decision records, the audits and the setup notes are public at
        github.com/simon-derock/constellation, under the MIT licence. Search, the graph, the algorithms and the replayable
        proofs run without a language model; Ask needs any one free model key.
      </p>
    </article>
  );
}

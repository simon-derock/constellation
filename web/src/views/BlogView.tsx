// the best-blog entry for Graph Hacks: what was built, how FalkorDB carries it, and what did not work
export function BlogView() {
  return (
    <article className="blog">
      <p className="blog-kicker">Graph Hacks · Constellation</p>
      <h1>Every answer with its proof, on one FalkorDB graph</h1>
      <p className="blog-lede">
        Constellation is a company brain. It answers questions about who owned what, who knew what and what caused
        what, and every answer comes with the exact queries that produced it. Anyone can re-run those queries and check
        the result hash. This post covers what I built, how FalkorDB carries it, and the numbers, including the ones
        that did not improve.
      </p>

      <h2>One graph, and time in it</h2>
      <p>
        The live tenant is FalkorDB's own public GitHub organisation: 8,135 issues and pull requests across 74
        repositories, with 347 people shown only as pseudonyms. No issue body is stored. Each state an item has held is
        a claim with a valid-from and a valid-to, so "what was true on day D" is a query, not a backup. When the source
        changes, the old claim is closed and linked to its replacement by a superseding edge. Nothing is overwritten.
        The graph holds 19,798 claims and 6,676 supersessions. The simulated company (Apex) sits in the same engine,
        so one deployment answers both.
      </p>

      <h2>FalkorDB does more than store</h2>
      <p>
        The brief asked for FalkorDB at the centre, so I used the parts of it that matter for the questions:
      </p>
      <ul>
        <li>
          <strong>Vector search.</strong> An HNSW index over title embeddings (cosine), queried by{" "}
          <code>db.idx.vector.queryNodes</code>.
        </li>
        <li>
          <strong>Full-text search.</strong> An index over titles, queried by <code>db.idx.fulltext.queryNodes</code>.
          Search fuses both arms by rank, and each arm that ran is a replayable query.
        </li>
        <li>
          <strong>Graph algorithms.</strong> PageRank for the most connected people, betweenness for the people who
          bridge others, weakly connected components, and shortest collaboration paths. Betweenness uses a fixed source
          sample: I found that a large sample exhausted a 3 GB engine, so it is kept just above the node count.
        </li>
        <li>
          <strong>Read-only by construction.</strong> Every proof runs through <code>GRAPH.RO_QUERY</code>, so the engine
          refuses writes even if a query were wrong.
        </li>
        <li>
          <strong>Isolation.</strong> Each memory principal gets its own graph cloned with <code>GRAPH.COPY</code>.
        </li>
      </ul>
      <p>
        The efficiency number: about 50,000 nodes across both tenants take 74 MB in memory, with the vector and
        full-text indexes included.
      </p>

      <h2>Proofs you can replay</h2>
      <p>
        An answer is a list of named catalogue queries, each with its parameters and the SHA-256 of what it returned.
        Replay re-runs those queries read-only and compares hashes. A changed result shows up as a mismatch on the exact
        query that changed. Vectors are part of the proof too: a search's query embedding is a parameter, so the search
        replays as well.
      </p>

      <h2>What did not work</h2>
      <p>
        I measured retrieval on EnterpriseRAG-Bench, 511,962 documents and 470 scored questions, with the judge-free hit
        rate. The results are in the README and the audits, and several ideas that seemed obvious lost:
      </p>
      <ul>
        <li>Dense embeddings with a small open model scored 0.557 hit@10, below keyword search at 0.745.</li>
        <li>Embedding whole documents instead of their first 2,400 characters helped by only 2.5 points.</li>
        <li>Pseudo-relevance feedback hurt, falling to 0.719.</li>
        <li>Passage-level reranking was worse than reranking document heads at the same depth.</li>
        <li>A query rewrite by a 4B open model hurt, to 0.498, because it invented specifics.</li>
      </ul>
      <p>
        The one large gain was Cohere's <code>rerank-v4.0-pro</code> over the fused candidates: hit@10 rose from 0.738 to
        0.881 (95% interval 0.848 to 0.907), and hit@1 from 0.502 to 0.751. The candidate pool caps the result near
        0.92, so the 99% target is not reached. I have not claimed it.
      </p>

      <h2>What is still short</h2>
      <p>
        EpistemicBench ran in full on Cohere's Command A: 0.705 answer accuracy over 78 questions, and no lookup
        returned anything outside the person's knowledge cone. Counterfactual questions are the weak track at 0.343,
        and the 0.99 target is not reached. The acceptance criteria are tracked in the repository: 16 of 38 are met by
        tests, and the rest are marked partly met, not met, not built, or cut, with reasons.
      </p>

      <h2>Try it</h2>
      <p>
        The source, the decision records, the audits and the setup notes are public at
        github.com/simon-derock/constellation. The graph, the search, the people ranking and the replayable proofs all
        run without a language model.
      </p>
    </article>
  );
}

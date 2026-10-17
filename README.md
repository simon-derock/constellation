# Constellation

**The company brain that proves every answer — what's true, who knew it, and when. Exact to the bit, replayable to the source, on FalkorDB.**

Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB). Entered in **Track 01 · Agents That Act**, **Track 02 · Agent Memory and Coordination** and **Track 03 · Company Brain**.

> **Status:** specification frozen, build in progress. Every number on this page will come from a recorded run; until then there are none. Live progress: [`STATE.md`](STATE.md) · full design: [`PLAN_SPEC.md`](PLAN_SPEC.md).

---

## Why it is different

Most company-knowledge agents retrieve text and hope. Constellation treats company memory as **visibility × time** and stores both in FalkorDB:

- **Valid time.** When a fact held, as half-open intervals on edges.
- **Transaction time.** When the company recorded it.
- **Visibility.** Who could see it, compiled into exact permission bitmaps.

So every answer is a **proof**: the read-only Cypher that ran, its parameters, the result hash, the cited spans down to the character or the audio millisecond, and the permission check that admitted each one.

| Wall | In one line |
|---|---|
| **Truth** | Scored by answer keys we did not write: EpistemicBench and EnterpriseRAG-Bench |
| **Bits** | Permissions as exact bitmaps; zero leaks is an invariant, proven by property tests |
| **Proof** | Any answer replays to the same bytes |
| **Voice** | Meetings exist as speech, so a decision links to the second it was spoken |
| **FalkorDB-native** | Algorithms as agent tools, `GRAPH.COPY` tenancy, `GRAPH.RO_QUERY` read path, MCP; the live tenant is FalkorDB's own organisation |

## Tracks

| Track | What Constellation does |
|---|---|
| **03 · Company Brain** | Docs, tickets, chats, code and meetings in one bitemporal graph. Who owned what on any day; who *engaged with* versus who was merely *exposed to* a fact; decisions traced to the exact span; claims superseded as the live tenant changes |
| **01 · Agents That Act** | A bounded agent whose tools are reviewed Cypher and FalkorDB algorithms served over MCP. It routes, escalates and files issues only after approval, and every step lands in a trace |
| **02 · Memory and Coordination** | Per-tenant and per-user memory graphs cloned with `GRAPH.COPY`: episodic, semantic and procedural layers, persistent sessions, handoffs, and compare-and-set writes with zero lost updates |

## Architecture

```mermaid
flowchart TB
  U["Browser"]:::client
  MC["MCP clients · IDEs · other agents"]:::client

  subgraph EDGE["Vercel · static web"]
    UI["React · Sigma.js<br/>Ask · Time · Explorer · Scoreboard · Live · Film"]:::edge
  end

  subgraph CORE["Render · one container · the only always-on compute"]
    API["FastAPI + FastMCP<br/>/api · /mcp"]:::core
    AG["Agent FSM<br/>plan · tools · verify · act"]:::core
    BR["Brain · Track 03<br/>owners · knowers · decisions · freshness"]:::core
    MEM["Memory · Track 02<br/>episodes · facts · procedures · handoffs"]:::core
    RT["Retrieval plane<br/>ACL bitmaps · full-text · vector · RRF · expansion"]:::core
    FDB[("FalkorDB 4.22<br/>brain:* and mem:* graphs<br/>bitmaps · streams")]:::db
  end

  subgraph EXT["Free external services"]
    WAI["Workers AI<br/>live LLM · Qwen3-Embedding queries<br/>reranker · speech-to-text"]:::ext
    CO["Cohere<br/>second-model runs · judge"]:::ext
    GH["GitHub · FalkorDB org<br/>live tenant source"]:::ext
    SNAP[("GitHub Releases<br/>snapshots + manifests")]:::store
    JRN[("Cloudflare D1<br/>memory journal")]:::store
  end

  subgraph BATCH["Kaggle · batch factory · never on the request path"]
    JOBS["chunk · Qwen3-Embedding · bm25 · extract<br/>speech twin · EmbeddingGemma 2 voice · eval-batch"]:::batch
  end

  subgraph SCHED["Schedulers"]
    GHA["GitHub Actions cron<br/>sync · probe · snapshot"]:::sched
    CFW["Cloudflare Worker cron<br/>health · alert"]:::sched
  end

  U --> UI
  UI -->|"/api · /mcp rewrite"| API
  MC -->|"MCP"| API
  API --> AG
  AG --> BR
  AG --> MEM
  BR --> RT
  RT -->|"GRAPH.RO_QUERY only"| FDB
  MEM -->|"compare-and-set writes"| FDB
  MEM -->|"append"| JRN
  AG -->|"locked model"| WAI
  AG -.->|"comparison runs"| CO
  RT -->|"query vector · rerank"| WAI
  API -->|"ETag sync"| GH
  JOBS -->|"sharded parquet + sha256"| SNAP
  SNAP -->|"restore on boot"| FDB
  JRN -->|"replay on boot"| FDB
  FDB -->|"BGSAVE"| SNAP
  GHA --> API
  CFW --> API

  classDef client fill:#f4f4f5,stroke:#71717a,color:#18181b
  classDef edge fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
  classDef core fill:#ede9fe,stroke:#7c3aed,color:#2e1065
  classDef db fill:#fef3c7,stroke:#d97706,color:#451a03,stroke-width:2px
  classDef ext fill:#ecfdf5,stroke:#059669,color:#064e3b
  classDef store fill:#ecfdf5,stroke:#059669,color:#064e3b
  classDef batch fill:#fce7f3,stroke:#db2777,color:#500724
  classDef sched fill:#f1f5f9,stroke:#475569,color:#0f172a
  style EDGE fill:#f0f9ff,stroke:#7dd3fc
  style CORE fill:#faf5ff,stroke:#c4b5fd
  style EXT fill:#f0fdf4,stroke:#86efac
  style BATCH fill:#fdf2f8,stroke:#f9a8d4
  style SCHED fill:#f8fafc,stroke:#cbd5e1
```

## How an answer is proven

```mermaid
sequenceDiagram
  autonumber
  actor U as Asker
  participant API as API or MCP
  participant ACL as ACL bitmaps
  participant AG as Agent FSM
  participant LLM as Locked model
  participant FDB as FalkorDB
  U->>API: ask(question, as_of, principal)
  API->>ACL: allow-list for principal on day D
  ACL-->>API: bitmap + sha256
  API->>AG: question + tool catalogue
  AG->>LLM: pick tool and typed arguments
  LLM-->>AG: owner_as_of(component, day)
  AG->>FDB: GRAPH.RO_QUERY owner_as_of
  FDB-->>AG: rows + result hash
  AG->>FDB: hybrid retrieval behind the bitmap
  FDB-->>AG: admitted spans only
  AG->>FDB: verify by replaying every cited query
  FDB-->>AG: hashes match
  AG->>LLM: phrase the answer from admitted spans
  LLM-->>AG: answer text
  AG-->>API: answer + proof + trace
  API-->>U: answer · spans · audio clips · replay link
```

## Graph data model

Brain graph, one per tenant (`brain:<tenant>`):

```mermaid
classDiagram
  direction LR
  class Person {
    +uuid pid
    +string alias
    +string kind
  }
  class Team {
    +string id
  }
  class Component {
    +string id
  }
  class Space {
    +string id
    +bitmap readers derived
  }
  class Artifact {
    +uuid aid
    +string kind
    +int day
    +datetime t_tx
    +uint32 ix
  }
  class Chunk {
    +uuid cid
    +int ord
    +string text
    +vecf32 emb
  }
  class Claim {
    +uuid kid
    +string predicate
    +string value
    +interval valid
    +datetime t_tx
    +string status
  }
  class Decision {
    +uuid did
    +string status
  }
  class Meeting {
    +uuid mid
  }
  class Utterance {
    +uuid uid
    +int t0_ms
    +int t1_ms
  }
  Person --> Team : MEMBER_OF from..to
  Person --> Component : OWNS from..to
  Person --> Person : ESCALATES_TO
  Person --> Space : CAN_READ from..to
  Person --> Artifact : AUTHORED · REVIEWED · ASSIGNED
  Artifact --> Space : IN
  Artifact --> Chunk : HAS_CHUNK
  Chunk --> Chunk : NEXT
  Artifact --> Artifact : REPLIES_TO · REFERENCES
  Chunk --> Person : MENTIONS
  Claim --> Chunk : EVIDENCED_BY start..end
  Claim --> Utterance : EVIDENCED_BY t0..t1
  Claim --> Claim : SUPERSEDES · CONTRADICTS
  Claim --> Component : ABOUT
  Decision --> Meeting : DECIDED_IN
  Decision --> Person : DECIDED_BY
  Decision --> Component : AFFECTS
  Meeting --> Utterance : HAS_UTTERANCE
  Utterance --> Person : SPOKEN_BY
```

Memory graph, one per user and session (`mem:<tenant>:<principal>`):

```mermaid
classDiagram
  direction LR
  class Session {
    +uuid sid
    +string principal
  }
  class Turn {
    +int n
    +string role
    +uuid proof_id
  }
  class Episode {
    +uuid eid
    +string task
    +int ver
  }
  class Fact {
    +uuid id
    +string value
    +int ver
  }
  class Procedure {
    +uuid id
    +string tool_plan
    +int verified_runs
  }
  class Agent {
    +string name
  }
  class Handoff {
    +uuid hid
    +string state_sha256
    +int ver
  }
  class Action {
    +uuid act_id
    +string kind
    +string status
  }
  Session --> Turn : HAS_TURN
  Turn --> Turn : NEXT
  Agent --> Episode : RECORDED
  Episode --> Fact : CONSOLIDATED_INTO
  Episode --> Procedure : DISTILLED_INTO
  Agent --> Handoff : HANDED_OFF
  Handoff --> Agent : TO
  Agent --> Action : PROPOSED
```

## The agent

```mermaid
stateDiagram-v2
  [*] --> Plan
  Plan --> Tool: tool chosen
  Tool --> Plan: evidence missing
  Tool --> Verify: evidence sufficient
  Plan --> Abstain: budget spent or no tool fits
  Verify --> Plan: hash mismatch
  Verify --> Answer: proof replays
  Verify --> Propose: action warranted
  Propose --> Await
  Await --> Execute: approved
  Await --> Answer: rejected
  Execute --> Answer
  Answer --> [*]
  Abstain --> [*]
  note right of Plan
    at most 5 planning calls
    identical tool calls refused
  end note
  note right of Await
    approval is a graph event
    execution idempotent on payload hash
  end note
```

The model chooses *what to ask*; it almost never writes query text. Reviewed catalogue queries come first, chained for multi-hop questions. Generated Cypher is a guarded last resort: it is parsed with `GRAPH.EXPLAIN`, checked against an allowlist, capped, run with `GRAPH.RO_QUERY`, and re-checked against the permission bitmap ([PLAN_SPEC §11](PLAN_SPEC.md)).

## Cypher the product relies on

```cypher
// owner_as_of — who owned a component on day D (half-open interval)
MATCH (p:Person)-[o:OWNS]->(c:Component {id: $component})
WHERE o.from <= $day AND (o.to IS NULL OR $day < o.to)
RETURN p.alias AS owner, o.from AS since, o.aid AS evidence
```

```cypher
// escalation_path — shortest escalation chain valid on day D
MATCH (a:Person {pid: $from}), (b:Person {pid: $to})
MATCH p = shortestPath((a)-[:ESCALATES_TO*..6]->(b))
WHERE all(r IN relationships(p) WHERE r.from <= $day AND (r.to IS NULL OR $day < r.to))
RETURN [n IN nodes(p) | n.alias] AS chain
```

The full catalogue, including the knowledge frontier, decision provenance, stale-claim detection and the algorithms used as tools, is in [PLAN_SPEC §7](PLAN_SPEC.md).

## Keeping knowledge current

```mermaid
sequenceDiagram
  autonumber
  participant CR as Scheduler
  participant SY as Sync
  participant GH as GitHub API
  participant FDB as FalkorDB
  participant CA as Answer cache
  CR->>SY: every 10 minutes
  SY->>GH: conditional GET with ETag and cursor
  GH-->>SY: changed issues and PRs
  SY->>FDB: MERGE change events as new claims
  FDB-->>SY: open claims with the same subject and predicate
  SY->>FDB: close old interval and link SUPERSEDES
  SY->>CA: invalidate answers that cite superseded claims
  Note over CA: stale-since marker visible within 10 minutes
```

## Data

| Tenant | Source | Licence |
|---|---|---|
| Apex Athletics | OrgForge simulated company, with the EpistemicBench questions | MIT |
| Redwood Inference | EnterpriseRAG-Bench: 511,962 documents and 500 questions | MIT |
| FalkorDB OSS (live) | Public metadata of the FalkorDB GitHub organisation, people pseudonymised | Public |

Only public and synthetic data is used. People appear as stable pseudonyms. Benchmark corpora are never re-published in bulk.

## Results

None yet. Each figure will link to the run that produced it, with official raw scores published alongside gold-audited scores.

## Running it

Setup instructions land with the first runnable build. The target is a single `docker compose up` that starts FalkorDB, the API and the web app.

## AI assistance

AI coding assistants were used during development, as the hackathon rules allow. Every change is reviewed, tested and understood by the author, who can explain the code, the graph model, the queries and the architecture decisions.

## Prior art

The author previously built *Stellium* (agentic GraphRAG on TigerGraph) and *Lunarbit* (evidence-verifiable GraphRAG on Neo4j). Constellation carries over their engineering discipline, not their code. All FalkorDB work here was built during the event.

## Licence

[MIT](LICENSE)

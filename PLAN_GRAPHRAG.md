# GraphRAG Implementation Plan

**Goal:** Replace non-deterministic flat context with a structured knowledge graph that gives agents stable, relationship-aware context — reducing LLM output variance while improving signal quality.

**Key constraint:** Determinism first. Every design choice prioritizes reproducibility. Regex over LLM extraction, snapshots over live queries, rules tables over heuristics.

---

## Architecture Summary

```
                    Existing Pipeline
                    ================
  Tiingo/FMP/FRED/Tavily → market_enrichment.py → enrichment_sections{}
  SEC filings → warehouse/db.py → filing_sections table
  peer_enrichment.py → peer_comparison section

                    New GraphRAG Layer
                    ==================
  enrichment_sections + filing_sections + peers
       │
       ▼
  graph_rag/extractors/     ←── regex + rules (no LLM)
       │
       ▼
  graph_nodes + graph_edges (SQLite, same DB)
       │
       ▼
  graph_rag/snapshot.py     ←── deterministic JSON snapshots
       │
       ▼
  graph_rag/context_formatter.py → enrichment_sections["graph_context"]
       │
       ▼
  agents/{dcf,risk,competitive,macro}.py consume it
```

---

## SQLite Schema (3 tables, same warehouse DB)

```sql
-- Typed nodes: companies, sectors, macro indicators
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id         TEXT PRIMARY KEY,       -- "company:AAPL", "sector:Technology", "macro:FEDFUNDS"
    node_type       TEXT NOT NULL,          -- COMPANY | SECTOR | INDUSTRY | MACRO_INDICATOR
    label           TEXT NOT NULL,          -- "Apple Inc.", "Federal Funds Rate"
    properties      TEXT DEFAULT '{}',      -- JSON: {market_cap, cik, ...}
    valid_from      TEXT,                   -- ISO date
    valid_to        TEXT,                   -- NULL = still active
    source_filing   TEXT,                   -- accession number
    updated_at      REAL NOT NULL
);

-- Typed, weighted, temporal edges
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id         TEXT PRIMARY KEY,       -- deterministic: "{source}|{type}|{target}|{period}"
    source_id       TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    edge_type       TEXT NOT NULL,          -- PEER | SUPPLIER | CUSTOMER | SECTOR_MEMBER |
                                            -- MACRO_SENSITIVE | COMPETES_WITH
    weight          REAL DEFAULT 1.0,       -- 0.0-1.0 confidence/strength
    properties      TEXT DEFAULT '{}',      -- JSON: {revenue_pct, industry_match_score, ...}
    period          TEXT NOT NULL,           -- "2025-Q4", "2025-FY"
    source_filing   TEXT,
    evidence        TEXT DEFAULT '',         -- extracted text snippet
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

-- Cached deterministic snapshots
CREATE TABLE IF NOT EXISTS graph_snapshots (
    snapshot_id     TEXT PRIMARY KEY,       -- "AAPL|2025-Q4"
    ticker          TEXT NOT NULL,
    period          TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,          -- full subgraph as JSON
    edge_count      INTEGER NOT NULL,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges(source_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges(target_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_nodes_type   ON graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON graph_snapshots(ticker, period);
```

**Why deterministic IDs:** `edge_id = "company:AAPL|SUPPLIER|company:TSMC|2025-FY"` means two runs extracting the same relationship produce the same row. Upserts are idempotent.

**Why `period` on edges:** Temporal versioning. Edges from a 2024-FY 10-K coexist with 2025-FY edges. Default context uses the most recent period only.

---

## Edge Types and Extraction Sources

| Edge Type | Source | Extraction Method | Deterministic? |
|---|---|---|---|
| `PEER` | `peer_enrichment.py` validated peers | Direct: already discovered + SEC-validated + scored | Yes (cached) |
| `SECTOR_MEMBER` | Yahoo/FMP sector + industry | Direct: company metadata | Yes |
| `MACRO_SENSITIVE` | Sector + rules table | Rules: `{(indicator, sector) → weight}` | Yes |
| `COMPETES_WITH` | Peer list + filing co-mentions | Merge: validated peers + regex on filings | Yes |
| `SUPPLIER` | 10-K `filing_sections` text | Regex: "sole supplier", "key vendor", "source from" | Yes |
| `CUSTOMER` | 10-K `filing_sections` text | Regex: "X% of revenue", "accounted for" | Yes |

### Macro Transmission Rules (fully deterministic)

```python
MACRO_TRANSMISSION = {
    ("FEDFUNDS", "Financial Services"): (0.9, "net interest margin expansion/compression"),
    ("FEDFUNDS", "Real Estate"):       (0.8, "mortgage rate sensitivity"),
    ("FEDFUNDS", "Technology"):        (0.5, "DCF discount rate, growth vs value rotation"),
    ("FEDFUNDS", "Consumer Cyclical"): (0.6, "consumer credit cost, auto/housing"),
    ("CPIAUCSL", "Consumer Defensive"):(0.7, "input cost pass-through, pricing power"),
    ("CPIAUCSL", "Energy"):            (0.5, "commodity price linkage"),
    ("UNRATE",   "Consumer Cyclical"): (0.7, "employment-driven spending"),
    ("UNRATE",   "Consumer Defensive"):(0.3, "staples less sensitive"),
    ("T10Y2Y",   "Financial Services"): (0.8, "yield curve steepness -> bank profitability"),
    ("BAMLH0A0HYM2", "all"):           (0.6, "credit stress indicator"),
}
```

### SEC Filing Extraction Patterns (no LLM)

```python
SUPPLY_CHAIN_PATTERNS = [
    r"(?P<entity>[A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+accounted\s+for\s+(?:approximately\s+)?(?P<pct>\d+)%",
    r"(?P<pct>\d+)%\s+of\s+(?:our\s+)?(?:total\s+)?revenue.*?(?P<entity>[A-Z][a-z]+)",
    r"(?:sole|single|primary|key)\s+(?:source|supplier|vendor).*?(?P<entity>[A-Z][a-z]+(?:\s[A-Z][a-z]+)*)",
    r"(?:we|the\s+company)\s+(?:purchase|source|procure).*?from\s+(?P<entity>[A-Z][a-z]+)",
]
```

Extracted names validated against SEC ticker registry (already loaded in `peer_enrichment.py`).

---

## Module Structure

```
graph_rag/
    __init__.py              # Public API: refresh_graph(), build_graph_context()
    schema.py                # SQLite table creation, migration
    nodes.py                 # Node CRUD (upsert, lookup)
    edges.py                 # Edge CRUD (upsert, query by source/target/type)
    query.py                 # Subgraph traversal (2-hop BFS from target ticker)
    snapshot.py              # Snapshot creation/cache, staleness check
    context_formatter.py     # Subgraph → compact agent-consumable text
    extractors/
        __init__.py          # run_all_extractors() pipeline
        peer_extractor.py    # Validated peers → PEER + COMPETES_WITH edges
        filing_extractor.py  # 10-K text → SUPPLIER/CUSTOMER edges
        macro_extractor.py   # Sector + rules → MACRO_SENSITIVE edges
        sector_extractor.py  # Company metadata → SECTOR_MEMBER edges
```

---

## Phase 1: Minimal Viable Graph (LOW effort, HIGH impact)

**Deps:** None. Uses only data already computed in the enrichment pipeline.

**Files to create:**
- `graph_rag/__init__.py` — public API: `refresh_graph(ticker, data)`, `build_graph_context(ticker)`
- `graph_rag/schema.py` — `ensure_graph_tables(conn)` with CREATE TABLE statements
- `graph_rag/nodes.py` — `upsert_node(conn, node_id, node_type, label, properties)`
- `graph_rag/edges.py` — `upsert_edge(conn, source, target, type, weight, period, evidence)`
- `graph_rag/extractors/__init__.py` — `run_extractors(ticker, data, conn)`
- `graph_rag/extractors/peer_extractor.py` — reads `peer_comparison` enrichment section, creates PEER edges
- `graph_rag/extractors/sector_extractor.py` — reads sector/industry from AnalysisData, creates SECTOR_MEMBER edges
- `graph_rag/extractors/macro_extractor.py` — sector + MACRO_TRANSMISSION rules → MACRO_SENSITIVE edges
- `graph_rag/query.py` — `query_subgraph(conn, ticker, max_depth=2)` → dict of edges by type
- `graph_rag/context_formatter.py` — `format_graph_context(subgraph, agent_name)` → str

**Files to modify:**
- `config.py` — add `enable_graph_rag: bool = False`, `graph_rag_max_chars: int = 1500`, `graph_rag_max_depth: int = 2`, `graph_rag_snapshot_ttl_hours: int = 24`
- `warehouse/db.py` — call `ensure_graph_tables()` in `_init_schema()` (line ~114)
- `orchestrator.py` — add `refresh_graph()` + `build_graph_context()` calls in `prepare_data()` (after enrichment, ~line 344 and ~451)
- `agents/dcf.py` — add `"graph_context"` to `enrichment_sections` tuple
- `agents/risk.py` — add `"graph_context"` to `enrichment_sections` tuple
- `agents/competitive.py` — add `"graph_context"` to `enrichment_sections` tuple
- `agents/macro.py` — add `"graph_context"` to `enrichment_sections` tuple

**New env vars:** `ENABLE_GRAPH_RAG=false` (off by default)

**Output format (example, ~400 chars):**
```
=== Knowledge Graph Context ===
[Peers] MSFT(0.92) GOOG(0.87) AMZN(0.71) META(0.68)
[Sector] Technology > Consumer Electronics > rank=1
[Macro Sensitivity] FEDFUNDS(0.5, DCF discount rate) | CPI(0.3) | UNRATE(0.3)
```

**Verification:**
1. `ENABLE_GRAPH_RAG=true python main.py AAPL` — graph_context section appears in agent inputs
2. Run twice — graph_context output is byte-identical between runs
3. `python scripts/test_reproducibility.py AAPL --runs 3` — measure variance reduction

**Integration risks:**
- `enrichment_max_chars` budget: graph_context (1500) + existing sections must fit in 10000. Current sections total ~8000. May need to trim `external_company` or `external_industry` by 500 chars to make room.
- Thread safety: `refresh_graph()` opens its own SQLite connection (following `WarehouseDB` pattern — never pass connections across threads).

---

## Phase 2: Filing Extraction (MEDIUM effort, MEDIUM impact)

**Deps:** Phase 1 complete.

**Files to create:**
- `graph_rag/extractors/filing_extractor.py` — regex patterns on `filing_sections` table text, entity resolution via SEC ticker map

**Files to modify:**
- `graph_rag/extractors/__init__.py` — add filing_extractor to pipeline
- `graph_rag/context_formatter.py` — add [Suppliers] and [Customers] blocks

**Output format addition:**
```
[Suppliers] TSMC(revenue_pct=25%, sole_source) Samsung(12%)
[Customers] No disclosed >10% concentration
[Supply Chain Risk] Single-source: TSMC (advanced node fab)
```

**Verification:**
1. Run on AAPL — should extract TSMC, Foxconn from 10-K supplier disclosures
2. Run on a customer-concentrated company (e.g., defense contractor) — should extract government customer edges
3. Validate all extracted entities resolve to real tickers via SEC registry

**Integration risks:**
- Filing text quality: `filing_sections` text may contain HTML artifacts from XBRL parsing. May need to strip tags before regex matching.
- Entity resolution false positives: "Apple" as a company name could match other things. SEC ticker map validation is the gate.
- No new dependencies required.

---

## Phase 3: Snapshots and Temporal Queries (LOW effort, MEDIUM impact)

**Deps:** Phase 1 complete.

**Files to create:**
- `graph_rag/snapshot.py` — `get_or_create_snapshot(conn, ticker, period)`, `invalidate_snapshot(conn, ticker)`

**Files to modify:**
- `graph_rag/query.py` — check snapshot cache before live query
- `graph_rag/__init__.py` — invalidate snapshot after `refresh_graph()`

**Design:**
- `build_graph_context()` checks `graph_snapshots` first
- If snapshot exists and is within TTL → return cached JSON → format → identical output every time
- If stale → query edges, create new snapshot, return
- `refresh_graph()` invalidates the snapshot for the ticker so next read rebuilds it

**Verification:**
1. Run analysis twice with no data changes — snapshot cache hit on second run, identical output
2. Add a new peer manually via SQL — snapshot invalidated, new peer appears on next run

---

## Phase 4: Graph-Guided Pinecone Retrieval (MEDIUM effort, HIGH impact)

**Deps:** Phase 1 + Phase 2 complete. Pinecone (`enable_rag`) also enabled.

**Concept:** Instead of flat vector search (`query_rag(ticker, generic_query)`), use graph traversal to construct targeted retrieval queries:

```python
# Before (flat RAG):
chunks = query_rag("AAPL", "financial analysis revenue earnings")

# After (graph-guided):
suppliers = graph.get_edges("company:AAPL", "SUPPLIER")  # → [TSMC, Samsung]
query = f"AAPL supply chain risk {' '.join(s.label for s in suppliers)} concentration"
chunks = query_rag("AAPL", query)
```

**Files to modify:**
- `rag_enrichment.py` — add `graph_guided_query()` that constructs queries from graph edges
- `market_enrichment.py` — use `graph_guided_query()` instead of `query_rag()` when graph is available

**Impact:** This bridges the gap between GraphRAG (structured relationships) and Pinecone (unstructured detail). Graph tells you *what* to look for; Pinecone finds the *specific text*. Both layers are deterministic for the same graph state.

---

## Phase 5: IC Weight Calibration from Graph (FUTURE)

**Deps:** Quant-only backtest (already built) + Phase 1-2 complete + 50+ paper trades.

**Concept:** Use graph structure as a feature in IC weight calibration. Companies with high supply chain concentration → weight risk agent higher. Companies in rate-sensitive sectors → weight macro agent higher. This connects the graph layer to the backtest engine.

**Not designed in detail yet.** Requires empirical data from backtest results.

---

## What Agents Receive (per-agent graph context)

| Agent | Graph sections included | Rationale |
|---|---|---|
| DCF | Peers, Suppliers, Macro Sensitivity | Supply chain risk affects terminal value, macro affects discount rate |
| Risk | Suppliers, Customers, Macro Sensitivity, Supply Chain Risk | Concentration risk, macro exposure |
| Competitive | Peers, Sector Position | Core competitive landscape |
| Macro | Macro Sensitivity, Sector Position | Transmission mechanisms |
| Earnings | — | Backward-looking, doesn't benefit from relationships |
| Pattern | — | Technical signals are price-derived |

---

## Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Database | SQLite (same warehouse DB) | No new infra, Railway-compatible, sufficient for 100s of nodes |
| Extraction | Regex + rules (no LLM) | Determinism is the entire point |
| Context delivery | Enrichment section | Zero changes to BaseAgent, follows existing patterns |
| Temporal versioning | `period` field on edges | Coexisting temporal snapshots, no edge deletion needed |
| Determinism | JSON snapshots | Structural guarantee, not behavioral — byte-identical output |
| Pinecone coexistence | Graph selects, Pinecone retrieves | Complementary: structured relationships + unstructured detail |

---

## Migration Path from Current Flat RAG

1. **Phase 1-3:** Build GraphRAG as a parallel system. `enable_graph_rag=true` adds the `graph_context` enrichment section. Pinecone RAG stays off (`enable_rag=false`).
2. **Measure:** Run reproducibility tests with GraphRAG on vs off. Quantify variance reduction.
3. **Phase 4:** If/when Pinecone is re-enabled, switch from flat queries to graph-guided queries.
4. **Long-term:** Graph becomes the primary context layer; Pinecone becomes a detail retrieval backend.

The two systems are additive, not competing. Graph provides stable structural context; Pinecone provides variable-but-rich unstructured context. The graph *reduces* Pinecone's contribution to variance by making retrieval queries more targeted and consistent.

---

## Implementation Order (effort vs impact)

| Rank | Phase | Effort | Impact | Notes |
|------|-------|--------|--------|-------|
| 1 | Phase 1: Peer + Sector + Macro extractors | 2-3 hrs | HIGH | Immediate variance reduction on peer context |
| 2 | Phase 3: Snapshots | 1 hr | MEDIUM | Locks in determinism guarantee |
| 3 | Phase 2: Filing extraction | 2-3 hrs | MEDIUM | Adds supply chain intelligence |
| 4 | Phase 4: Graph-guided Pinecone | 2 hrs | HIGH | Only relevant when RAG is re-enabled |
| 5 | Phase 5: IC calibration | TBD | HIGH | Needs backtest data first |

**Total for Phases 1-3:** ~6 hours of implementation. No new dependencies. No new API calls. No new infrastructure.

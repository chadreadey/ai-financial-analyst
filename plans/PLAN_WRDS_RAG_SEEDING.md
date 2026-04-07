# WRDS Data Seeding for Pinecone + Supabase

**Created:** 2026-04-07
**Depends on:** PLAN_WRDS_INTEGRATION.md Phases 1-2 (WRDSClient + point-in-time store)
**Goal:** Upgrade the RAG knowledge base and warehouse from retail-grade data (FMP snapshots, yfinance) to institutional-grade data (WRDS Compustat, IBES, CRSP) — making the AI agents' context grounding dramatically richer and point-in-time correct.

---

## Why This Matters

Right now your RAG pipeline feeds agents SEC filing sections (10-K/10-Q text) and FMP financial snapshots. This is good but has two gaps:

1. **The financial snapshots are NOT point-in-time.** FMP returns the latest data — during backtesting, agents see numbers that weren't available at decision time. This is lookahead bias in the qualitative layer.

2. **No earnings estimate context.** Your agents analyze a company without knowing what the Street expects. Earnings surprise (actual vs. consensus) is one of the strongest cross-sectional predictors in finance, and your agents can't see it.

WRDS fixes both. Compustat has `rdq` (report date of quarterly earnings) for point-in-time filtering. IBES has consensus estimates with `statpers` (statement period) dates. Seeding these into Pinecone and Supabase gives every agent access to institutional-quality context.

---

## Architecture: What Goes Where

| Data | Store | Namespace/Table | Why There |
|------|-------|----------------|-----------|
| Quarterly financials (Compustat) | **Supabase** `xbrl_facts` table | — | Structured data, needs SQL queries for backtest signals |
| Quarterly financials (text summaries) | **Pinecone** `financial_ts` namespace | Per-ticker vectors | RAG context for LLM agents — natural language summaries |
| Earnings estimates (IBES consensus) | **Supabase** new `estimates` table | — | Structured data for SUE/ERM signal computation |
| Earnings estimates (text summaries) | **Pinecone** `financial_ts` namespace | Per-ticker vectors | RAG context — "Street expects $X EPS, revised up from $Y" |
| Analyst detail (IBES per-analyst) | **Supabase** new `analyst_estimates` table | — | Dispersion signal, revision tracking |
| CRSP identifiers + delistings | **Supabase** new `security_master` table | — | Survivorship-free universe construction |
| Macro data (FRED via WRDS) | **Supabase** `macro_series` table | — | Already exists, but WRDS version is higher quality |
| Macro summaries | **Pinecone** `macro_ts` namespace | Global vectors | Already working — just improve data quality |

---

## Phase 1: Supabase Schema Extensions

### New Tables

```sql
-- IBES consensus estimates (point-in-time)
CREATE TABLE IF NOT EXISTS estimates (
    ticker TEXT NOT NULL,
    metric TEXT NOT NULL,          -- 'eps', 'revenue', 'ebitda'
    period_end DATE NOT NULL,      -- fiscal period end
    statpers DATE NOT NULL,        -- statement date (when consensus was published)
    mean_est REAL,
    median_est REAL,
    high_est REAL,
    low_est REAL,
    num_est INTEGER,
    std_dev REAL,
    actual REAL,                   -- from ibes.actu_epsus (NULL until reported)
    announce_date DATE,            -- from ibes.actu_epsus
    surprise REAL,                 -- actual - mean_est (computed)
    surprise_pct REAL,             -- (actual - mean_est) / abs(mean_est)
    source TEXT DEFAULT 'wrds:ibes',
    commercial_replacement TEXT DEFAULT 'FMP /analyst-estimates ($29-79/mo) — consensus only, no per-analyst',
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, metric, period_end, statpers)
);

-- IBES per-analyst detail (for dispersion and revision signals)
CREATE TABLE IF NOT EXISTS analyst_estimates (
    ticker TEXT NOT NULL,
    analyst_id TEXT NOT NULL,      -- ibes.detu_epsus.analys
    broker TEXT,                   -- ibes.detu_epsus.estimator
    metric TEXT NOT NULL,
    period_end DATE NOT NULL,
    estimate_date DATE NOT NULL,   -- ibes.detu_epsus.anndats
    estimate_value REAL NOT NULL,
    source TEXT DEFAULT 'wrds:ibes',
    commercial_replacement TEXT DEFAULT 'Visible Alpha or Estimize ($299/mo) — no retail equivalent',
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, analyst_id, metric, period_end, estimate_date)
);

-- CRSP security master for survivorship-free universe
CREATE TABLE IF NOT EXISTS security_master (
    permno INTEGER NOT NULL,
    ticker TEXT,
    comnam TEXT,                   -- company name
    gvkey TEXT,                    -- Compustat link
    ibes_ticker TEXT,              -- IBES link  
    start_date DATE,
    end_date DATE,                 -- NULL if still active
    delist_code INTEGER,
    delist_ret REAL,               -- delisting return (critical for short validation)
    exchange TEXT,
    sic_code TEXT,
    source TEXT DEFAULT 'wrds:crsp',
    commercial_replacement TEXT DEFAULT 'Tiingo + manual mapping ($0)',
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (permno)
);
```

**Implementation:** Add to `warehouse/db.py` schema creation. Dual-backend (Supabase PostgreSQL / SQLite fallback) already handled by existing abstraction.

---

## Phase 2: WRDS → Supabase ETL

### 2.1 Compustat Quarterly → `xbrl_facts`

Your `xbrl_facts` table already stores structured financial data. WRDS Compustat quarterly (`comp.fundq`) is a strict upgrade:

```python
# In wrds_puller.py (from PLAN_WRDS_INTEGRATION.md)
COMPUSTAT_QUERY = """
SELECT gvkey, datadate, rdq, fyearq, fqtr,
       revtq, cogsq, xsgaq, oibdpq, niq,
       atq, ltq, ceqq, dlttq, dlcq,
       oancfy, capxy, cheq, cshoq,
       prccq  -- price at quarter end
FROM comp.fundq
WHERE gvkey IN ({gvkeys})
  AND datadate >= '{start_date}'
  AND datafmt = 'STD' AND indfmt = 'INDL' AND consol = 'C' AND popsrc = 'D'
ORDER BY gvkey, datadate
"""
```

**Point-in-time key:** Use `rdq` (report date) NOT `datadate` (period end). Data is only available to agents/signals after `rdq`. Where `rdq` is NULL (~15% pre-2010), fall back to `datadate + 45 days` and tag `rdq_inferred=True`.

**Mapping:** gvkey → ticker via `comp.security` or CRSP CCM link table.

### 2.2 IBES Consensus → `estimates`

```python
IBES_CONSENSUS_QUERY = """
SELECT ticker, measure, fpedats, statpers,
       meanest, medest, highest, lowest, numest, stdev
FROM ibes.statsumu_epsus
WHERE ticker IN ({ibes_tickers})
  AND fpedats >= '{start_date}'
  AND fpi IN ('1', '2')  -- current and next quarter
  AND measure = 'EPS'
ORDER BY ticker, fpedats, statpers
"""

IBES_ACTUALS_QUERY = """
SELECT ticker, measure, pends, anndats, value
FROM ibes.actu_epsus
WHERE ticker IN ({ibes_tickers})
  AND pends >= '{start_date}'
  AND measure = 'EPS'
"""
```

**Join logic:** Match actuals to consensus by `ticker + fpedats ≈ pends`. Compute `surprise = actual - mean_est` and `surprise_pct`.

### 2.3 CRSP Security Master → `security_master`

```python
CRSP_SECURITY_QUERY = """
SELECT a.permno, b.ticker, a.comnam, c.gvkey, 
       a.namedt AS start_date, a.nameendt AS end_date,
       a.exchcd AS exchange, a.siccd AS sic_code
FROM crsp.dsenames a
LEFT JOIN crsp.dsenames b ON a.permno = b.permno AND b.nameendt = (
    SELECT MAX(nameendt) FROM crsp.dsenames WHERE permno = a.permno)
LEFT JOIN crsp.ccmxpf_linktable c ON a.permno = c.lpermno 
    AND c.linktype IN ('LU', 'LC') AND c.usedflag = 1
WHERE a.nameendt >= '{start_date}'
"""

CRSP_DELIST_QUERY = """
SELECT permno, dlstdt, dlstcd, dlret
FROM crsp.dsedelist
WHERE dlstdt >= '{start_date}'
"""
```

**Purpose:** Survivorship-free universe construction. When backtesting, filter stocks that were in the index as-of each rebalance date, including those that later delisted.

---

## Phase 3: WRDS → Pinecone Vector Seeding

This is where WRDS data becomes RAG context for the LLM agents. Reuse your existing `warehouse/financial_vectors.py` pattern but with richer data.

### 3.1 Enriched Financial Vectors

**Current vector text (from FMP):**
```
AAPL Q1 2024 Financial Snapshot
Revenue: $90.8B (YoY: +2.1%)
Net Income: $23.6B (Margin: 26.0%)
...
```

**WRDS-enriched vector text:**
```
AAPL Q1 2024 Financial Snapshot (reported 2024-02-01)
Revenue: $119.6B (YoY: +2.1%, QoQ: -11.2%)
Net Income: $33.9B (Margin: 28.4%)
Operating Cash Flow: $39.9B (FCF: $32.1B)
Total Debt: $108.0B | Cash: $40.8B | Net Debt: $67.2B
Shares Outstanding: 15.44B

EARNINGS CONTEXT:
Street consensus (as of 2024-01-15): $2.10 EPS from 28 analysts
Range: $1.95 - $2.25 | Std Dev: $0.07
Actual: $2.18 EPS (BEAT by $0.08, +3.8%)
Revision trend (3mo): consensus UP from $2.02 → $2.10 (+4.0%)
Analyst dispersion: LOW (std/mean = 3.3%) — high conviction

QUALITY METRICS:
ROE: 171.9% | ROIC: 56.2% | Gross Margin: 45.9%
Altman Z-Score: 8.2 (safe zone >3.0)
Accrual Ratio: -2.1% (cash earnings > accounting earnings — good)
```

This is dramatically richer context for the LLM agents. They can now see:
- What the Street expected vs. what happened
- Whether estimates were revised up or down going in
- How much analyst disagreement existed
- Quality/safety metrics beyond just revenue/income

### 3.2 Vector Schema

**File:** Extend `warehouse/financial_vectors.py`

```python
def build_wrds_financial_vector(ticker: str, quarter_data: dict, estimate_data: dict) -> dict:
    """Build enriched financial vector from WRDS Compustat + IBES data."""
    text = f"""
{ticker} {quarter_data['period']} Financial Snapshot (reported {quarter_data['rdq']})
Revenue: ${quarter_data['revtq']/1e9:.1f}B (YoY: {quarter_data['rev_yoy']:.1%})
Net Income: ${quarter_data['niq']/1e9:.1f}B (Margin: {quarter_data['net_margin']:.1%})
Operating Cash Flow: ${quarter_data['oancfq']/1e9:.1f}B
...
EARNINGS CONTEXT:
Street consensus (as of {estimate_data['statpers']}): ${estimate_data['meanest']:.2f} EPS from {estimate_data['numest']} analysts
Actual: ${estimate_data['actual']:.2f} EPS ({estimate_data['surprise_direction']} by ${abs(estimate_data['surprise']):.2f}, {estimate_data['surprise_pct']:.1%})
Revision trend (3mo): consensus {estimate_data['revision_direction']} {estimate_data['revision_pct']:.1%}
Analyst dispersion: {estimate_data['dispersion_label']} (std/mean = {estimate_data['cv']:.1%})
"""
    return {
        "_id": f"{ticker}_fts_{quarter_data['period']}",
        "text": text.strip()[:4000],
        "ticker": ticker,
        "period": quarter_data["period"],
        "rdq": quarter_data["rdq"],
        "source": "wrds:comp.fundq+ibes.statsumu_epsus",
    }
```

### 3.3 Upsert to Pinecone

Reuse `warehouse/embedder.py` pattern. Upsert to `financial_ts` namespace. The vector ID format (`{TICKER}_fts_{YYYYQQ}`) means WRDS vectors **replace** the existing FMP-sourced vectors — same IDs, richer content.

---

## Phase 4: Backtest-Time RAG (Point-in-Time)

**Critical:** During backtesting, RAG queries must respect point-in-time. An agent deciding on 2023-06-01 should NOT see Q1 2024 earnings data.

**Implementation:** Add `as_of_date` filtering to `rag_enrichment.py`:

```python
def query_rag(ticker: str, query: str = "", top_k: int = 0, as_of_date: str = None) -> list[dict]:
    """Query Pinecone with optional point-in-time filter."""
    filter_dict = {"ticker": {"$eq": ticker}}
    if as_of_date:
        filter_dict["rdq"] = {"$lte": as_of_date}  # only data reported before decision date
    # ... rest of existing query logic
```

This ensures:
- In **production** (no `as_of_date`): agents see all available data (current behavior)
- In **backtesting** (with `as_of_date`): agents only see data that was actually available — no lookahead

---

## Seeding Sequence

| Step | What | Data Size | Time Est |
|------|------|-----------|----------|
| 1 | Run PLAN_WRDS_INTEGRATION.md Phases 1-2 (connection + PIT store) | — | Already planned |
| 2 | Create Supabase `estimates`, `analyst_estimates`, `security_master` tables | Schema only | 30 min |
| 3 | ETL: Compustat quarterly → Supabase `xbrl_facts` (10 years, top 500 stocks) | ~200K rows | 1-2 hours |
| 4 | ETL: IBES consensus → Supabase `estimates` | ~500K rows | 2-3 hours |
| 5 | ETL: IBES per-analyst → Supabase `analyst_estimates` | ~2M rows | 3-4 hours |
| 6 | ETL: CRSP security master → Supabase `security_master` | ~30K rows | 30 min |
| 7 | Build enriched financial vectors from Supabase data | ~10K vectors | 1-2 hours |
| 8 | Upsert enriched vectors to Pinecone `financial_ts` namespace | Replaces existing | 30 min |
| 9 | Add `as_of_date` filtering to `rag_enrichment.py` | Code change | 1 hour |
| 10 | Validate: run agent on AAPL with as_of_date=2024-01-01, verify no future data | — | 30 min |

**Total incremental effort beyond existing WRDS plan:** ~8-12 hours
**Pinecone cost impact:** Negligible (replacing existing vectors, not adding new namespace)
**Supabase cost impact:** ~3M rows total — well within free/hobby tier

---

## What This Unlocks

1. **Point-in-time correct agent analysis** — no more lookahead bias in the qualitative layer
2. **Earnings context in every agent prompt** — "Street expected $2.10, you beat by $0.08" is dramatically better context than just "EPS was $2.18"
3. **Revision and dispersion signals visible to agents** — they can see whether the Street is converging or diverging on a name
4. **Survivorship-free universe** — agents and backtests operate on the stocks that actually existed at each point in time
5. **Foundation for the earnings-based quant signals** (PLAN_WRDS_INTEGRATION.md Phase 4) — the SUE, ERM, and dispersion signals need this same data in Supabase

This is your RAG moat. TradingAgents feeds yfinance into prompts. You'll feed point-in-time Compustat + IBES consensus + analyst detail + SEC filing sections into a vector-grounded RAG pipeline. That's a qualitative data advantage no open-source competitor has.

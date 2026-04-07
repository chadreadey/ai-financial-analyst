# WRDS Integration Plan

## Goal
Rebuild the signal stack with earnings-based signals from WRDS (IBES + Compustat) to generate genuine factor-adjusted alpha. The current technical signals have zero cross-sectional IC and zero factor-adjusted alpha.

## Problem Statement (updated 2026-04-07 after stress test)
- **Signal stack is broken:** 5 technical signals are redundant close-price transformations. Only OBV has independent predictive power (residual IC t=1.82). Factor-adjusted alpha t=1.08 (not significant).
- **Alpha source identified:** Literature review confirms earnings revision momentum (ERM) is the #1 independent alpha signal. Novy-Marx (2015) proved ERM subsumes price momentum. IC 0.04-0.08, survives FF5+Mom.
- **Requires IBES data:** ERM needs `ibes.statsumu_epsus` with `anndats` for point-in-time consensus. SUE needs `comp.fundq` with `rdq`. Neither available from FMP/Tiingo.
- Current fundamental cache is a **single snapshot** — every rebalance date sees the same latest quarter (severe lookahead bias)
- Tiingo free tier capped at DOW 30, ~14 quarters. FMP free tier at 250 calls/day

## Revised Signal Architecture (target)

| Signal | Weight | Source | Family | WRDS Table |
|--------|--------|--------|--------|-----------|
| **OBV Trend** | 20% | Volume | Volume | Not needed (price cache) |
| **SMA Trend** | 0% scored, gate only | Price | Trend | Not needed |
| **Earnings Revision (ERM)** | 30% | IBES | Earnings | `ibes.statsumu_epsus` |
| **SUE** | 20% | Compustat + IBES | Earnings | `comp.fundq` + `ibes.actu_epsus` |
| **Analyst Dispersion** | 15% | IBES | Uncertainty | `ibes.statsumu_epsus` |
| **Fundamental Quality** | 15% | Compustat | Fundamental | `comp.fundq` |

**Dropped:** Mean Reversion (subsumed), Bollinger (ρ=0.86 with RSI), RSI (wrong-sign IC), 52-Week High (subsumed by SMA)

## Validation Criteria
- CPCV PBO must stay < 10% (currently 0%)
- Factor-adjusted alpha t-stat must reach > 2 (currently 1.08)
- Median OOS Sharpe must hold > 0.9 (currently 1.04)
- Mean alpha vs SPY must improve from -4.4%

## WRDS License Constraint
**Academic use only.** Every data pull must be tagged with its commercial replacement and cost so WRDS can be deprecated when reaching commercial threshold. Tags travel with the data from pull → store → signal → audit.

---

## Architecture

### Core Design Decisions

1. **Separate SQLite database** (`.wrds_cache.db`) — not the existing `.fmp_cache.db`. WRDS data is bulk-loaded reference data; FMP cache is ephemeral live data. Different lifecycles.

2. **Point-in-time filtering in the provider, not the signal layer.** Signal code (`compute_quality_score`, `compute_earnings_revision_score`) stays unchanged — the provider returns "what you would have seen on this date." Existing FMP path continues to work for live use with `as_of_date=None`.

3. **FundamentalProvider protocol** — formal interface that both `_CacheBackedFMP` and the new `WRDSPointInTimeStore` satisfy. The backtest engine selects provider based on config.

4. **Ticker → gvkey → IBES ticker mapping** built once during ETL, stored as `ticker_link` table, denormalized into every data table.

### File Structure

```
quant/
  wrds_client.py          # NEW — Connection wrapper
  wrds_puller.py          # NEW — Dataset-specific pull functions + commercial tags
  wrds_store.py           # NEW — Point-in-time SQLite store
  fundamental_provider.py # NEW — Protocol + provider registry
  fundamentals.py         # MODIFY — accept as_of_date parameter
  fmp_cache.py            # UNCHANGED
  backtest.py             # MODIFY — pass reb_date to fundamental calls
scripts/
  seed_wrds.py            # NEW — One-time WRDS data pull + ETL
```

---

## Commercial Replacement Tags

Every WRDS data pull embeds a tag constant:

```python
COMPUSTAT_TAG = {
    "source": "wrds:comp.fundq",
    "replacement": "FMP /stable/income-statement?period=quarter + /stable/balance-sheet-statement?period=quarter",
    "cost": "$29/mo FMP Starter (250 req/day) or $79/mo FMP Pro (unlimited)",
    "field_mapping": {
        "atq": "totalAssets",
        "ceqq": "totalStockholdersEquity",
        "ltq": "totalLiabilities",
        "dlcq": "shortTermDebt",
        "dlttq": "longTermDebt",
        "cheq": "cashAndCashEquivalents",
        "actq": "totalCurrentAssets",
        "lctq": "totalCurrentLiabilities",
        "saleq": "revenue",
        "niq": "netIncome",
        "ibq": "incomeBeforeExtraItems (no direct FMP equivalent)",
        "oancfy": "operatingCashFlow (YTD — FMP provides quarterly)",
        "epsfxq": "eps",
        "rdq": "reportDate — NO FMP EQUIVALENT (must derive from filingDate + lag)",
    },
    "notes": "rdq (report date of quarterly earnings) is when the filing became public. This is the point-in-time key. FMP has no equivalent — filingDate is close but not identical. This is the hardest field to replace.",
}

IBES_TAG = {
    "source": "wrds:ibes.detu_epsus + ibes.actu_epsus",
    "replacement": "Visible Alpha (institutional) or Estimize ($299/mo) or FMP /analyst-estimates (limited)",
    "cost": "No direct retail equivalent at comparable depth. FMP analyst-estimates lacks per-analyst detail and anndats.",
    "field_mapping": {
        "anndats": "NO FMP EQUIVALENT (announcement date of individual estimate)",
        "value": "epsAvg (FMP gives consensus only, not per-analyst)",
        "analys": "NO FMP EQUIVALENT (analyst identifier)",
        "fpedats": "date (fiscal period end)",
    },
    "notes": "IBES is the primary reason for WRDS access. anndats enables real revision momentum — when did the consensus shift? FMP only gives current consensus, not the history of changes.",
}

CRSP_TAG = {
    "source": "wrds:crsp.ccmxpf_linktable + crsp.dsenames",
    "replacement": "Tiingo (already in stack) + manual ticker mapping",
    "cost": "$0 — used only for identifier crosswalk, not price data",
    "notes": "CRSP adds delisting-adjusted returns (matters for short validation). Tiingo/Alpaca miss delistings.",
}
```

Tags are stored in a `commercial_tags` table in the WRDS SQLite database for auditability.

---

## Phase 1: Connection + Raw Pull (Small)

**Depends on:** Nothing
**Deliverable:** Can query WRDS and save raw data locally

### Create
- `quant/wrds_client.py` — `WRDSClient` class wrapping `wrds.Connection()`. Context manager, query method returning DataFrame.
- `quant/wrds_puller.py` — Three pull functions with embedded commercial tags:
  - `pull_compustat_quarterly(client, tickers, start_year=2013)` → DataFrame with gvkey, datadate, rdq, atq, ceqq, ltq, dlcq, dlttq, cheq, actq, lctq, saleq, niq, ibq, oancfy, epsfxq, capxy
  - `pull_ibes_estimates(client, tickers, start_year=2013)` → DataFrame with ticker, fpedats, anndats, value, analys
  - `pull_crsp_compustat_link(client, tickers)` → DataFrame with ticker, gvkey, permno, linkdt, linkenddt

### New env vars
- `WRDS_USERNAME` — WRDS account username

### Verify
```bash
python -c "from quant.wrds_client import WRDSClient; c = WRDSClient(); print(c.query('SELECT COUNT(*) FROM comp.fundq'))"
```

---

## Phase 2: Point-in-Time SQLite Store (Medium)

**Depends on:** Phase 1
**Deliverable:** Queryable local store with point-in-time semantics

### Create
- `quant/wrds_store.py` — `WRDSPointInTimeStore` class

**Schema:**
```sql
CREATE TABLE compustat_quarterly (
    gvkey     TEXT NOT NULL,
    ticker    TEXT NOT NULL,
    datadate  TEXT NOT NULL,   -- fiscal quarter end
    rdq       TEXT NOT NULL,   -- report date = when public
    data_json TEXT NOT NULL,   -- all numeric fields as JSON
    PRIMARY KEY (gvkey, datadate)
);
CREATE INDEX idx_compustat_pit ON compustat_quarterly(ticker, rdq);

CREATE TABLE ibes_consensus (
    ticker    TEXT NOT NULL,
    fpedats   TEXT NOT NULL,   -- forecast period end
    stat_date TEXT NOT NULL,   -- date this consensus was computed
    eps_mean  REAL,
    eps_median REAL,
    n_analysts INTEGER,
    PRIMARY KEY (ticker, fpedats, stat_date)
);
CREATE INDEX idx_ibes_pit ON ibes_consensus(ticker, stat_date);

CREATE TABLE ticker_link (
    ticker     TEXT PRIMARY KEY,
    gvkey      TEXT,
    permno     INTEGER,
    ibes_ticker TEXT,
    link_start TEXT,
    link_end   TEXT
);

CREATE TABLE commercial_tags (
    table_name TEXT PRIMARY KEY,
    tag_json   TEXT NOT NULL
);
```

**Key methods:**
```python
class WRDSPointInTimeStore:
    def get_fundamentals_as_of(self, ticker, as_of_date, n_quarters=8) -> list[dict]
        # SELECT ... WHERE ticker=? AND rdq <= ? ORDER BY rdq DESC LIMIT ?
    
    def get_ibes_consensus_as_of(self, ticker, as_of_date, n_periods=4) -> list[dict]
        # SELECT ... WHERE ticker=? AND stat_date <= ? ORDER BY stat_date DESC LIMIT ?
    
    def ingest_compustat(self, df) -> int
    def ingest_ibes(self, df) -> int
    def ingest_links(self, df) -> int
```

### Create
- `scripts/seed_wrds.py` — One-time ETL script
  1. Connect to WRDS
  2. Pull identifier crosswalk (CRSP-Compustat link + IBES ticker map)
  3. Pull Compustat quarterly for target tickers (liquid_50 + DOW 30 + S&P 500 top 100)
  4. Pull IBES detail estimates, aggregate to consensus per (ticker, fpedats, stat_date)
  5. Ingest into `.wrds_cache.db`
  6. Store commercial tags
  7. Print summary: row counts, date ranges, commercial replacement costs

### Verify
```python
store = WRDSPointInTimeStore()
# Should return Q3 2022 filing (rdq ~Oct 2022), not Q4 2022
data = store.get_fundamentals_as_of("AAPL", as_of_date="2022-12-01", n_quarters=4)
assert data[0]["datadate"] <= "2022-09-30"  # Q3 fiscal end
assert data[0]["rdq"] <= "2022-12-01"       # report date before as_of
```

---

## Phase 3: FundamentalProvider Protocol + Backtest Integration (Medium)

**Depends on:** Phase 2
**Deliverable:** Backtest engine uses point-in-time WRDS data at each rebalance

### Create
- `quant/fundamental_provider.py` — Protocol definition

```python
@runtime_checkable
class FundamentalProvider(Protocol):
    def get_balance_sheet_quarterly(
        self, ticker: str, limit: int = 4, as_of_date: date | None = None
    ) -> list[dict]: ...
    
    def get_income_statement_quarterly(
        self, ticker: str, limit: int = 8, as_of_date: date | None = None
    ) -> list[dict]: ...
    
    def get_analyst_estimates(
        self, ticker: str, limit: int = 4, as_of_date: date | None = None
    ) -> list[dict]: ...
```

### Modify
- `quant/fundamentals.py`:
  - `compute_quality_score(ticker, provider, as_of_date=None)` — pass as_of_date through
  - `compute_earnings_revision_score(ticker, provider, as_of_date=None)` — pass as_of_date through
  - `compute_fundamental_scores(tickers, provider, as_of_date=None)` — new unified entry point
  - `_CacheBackedFMP` gains `as_of_date` param (ignored — always returns latest, as before)

- `quant/backtest.py`:
  - `BacktestConfig` gains `fundamental_provider: str = "fmp"` (or `"wrds"`)
  - Module-level `_wrds_store = None` singleton, lazy-init alongside `_fmp_cache`
  - Lines 1704-1709 and 2094-2098: pass `as_of_date=reb_date` to `compute_fundamental_scores`
  - Provider selection: if `config.fundamental_provider == "wrds"`, use `_wrds_store`; else use `_CacheBackedFMP`

- `scripts/run_backtest.py`:
  - Add `--fundamental-provider wrds|fmp` flag (default: fmp)

### Verify
Run the same gold standard backtest with `--fundamental-provider wrds` and confirm:
1. Zero lookahead: no rebalance date should use a filing with `rdq` after that date
2. Signals change across windows (unlike the static FMP cache)
3. Results differ from the snapshot-based run (they should — the snapshot had lookahead bias)

---

## Phase 4: New Signal Stack — ERM, SUE, Dispersion (High priority)

**Depends on:** Phase 3
**Deliverable:** Three new earnings-based signals replacing the broken technical signals, backtestable with CPCV

This is the highest-value phase. The stress test proved the technical signals have zero IC; the literature review identified ERM as the #1 independent alpha source.

### Create: `quant/earnings_signals.py` (new file)

```python
def compute_erm_score(
    ticker: str, provider: FundamentalProvider, as_of_date: date = None,
    lookback_days: int = 63,
) -> tuple[float, dict]:
    """
    Earnings Revision Momentum (Novy-Marx 2015).
    
    ERM = (consensus_EPS_now - consensus_EPS_3mo_ago) / |consensus_EPS_3mo_ago|
    Uses IBES statsumu_epsus FY1 consensus with anndats for point-in-time.
    Documented IC: 0.04-0.08 monthly. Survives FF5+Mom.
    """

def compute_sue_score(
    ticker: str, provider: FundamentalProvider, as_of_date: date = None,
) -> tuple[float, dict]:
    """
    Standardized Unexpected Earnings (Bernard & Thomas 1989).
    
    SUE = (EPS_q - EPS_{q-4}) / std(EPS_q - EPS_{q-4}) over 8 quarters.
    Uses Compustat fundq (epspiq) with rdq for point-in-time.
    Captures post-earnings announcement drift.
    """

def compute_dispersion_score(
    ticker: str, provider: FundamentalProvider, as_of_date: date = None,
) -> tuple[float, dict]:
    """
    Analyst Dispersion (Diether, Malloy, Scherbina 2002).
    
    Dispersion = std(analyst estimates) / |mean(analyst estimates)|
    HIGH dispersion → NEGATIVE signal (overvaluation under disagreement).
    Uses IBES statsumu_epsus (stdev, meanest, numest). Requires numest >= 3.
    """
```

### Modify
- `quant/backtest.py` — new overlay blend function `blend_earnings_signals()` called after existing overlays
- `BacktestConfig` — add `enable_earnings_signals: bool = False`, `erm_weight: float = 0.30`, `sue_weight: float = 0.20`, `dispersion_weight: float = 0.15`
- `SignalVector` — demote SMA to gate-only (weight=0), drop MR/BB/RSI weights to 0, keep OBV at 0.20
- `scripts/run_backtest.py` — add `--enable-earnings-signals` flag

### Verify
1. Compute cross-sectional IC for each new signal on liquid_50 (must have t > 2)
2. Factor-attribute the new signal stack (FF5+Mom alpha t must reach > 2)
3. Run CPCV — PBO must stay < 10%, median Sharpe must hold > 0.9
4. Compare alpha vs SPY against the -4.4% baseline

---

## Phase 4b: Short-Specific Fundamental Signals (Medium)

**Depends on:** Phase 3
**Deliverable:** Three academic short signals computed from Compustat, backtestable

These are signals with documented predictive power for identifying shorts, computable entirely from Compustat quarterly data:

### Signal 1: Altman Z-Score (distress detection)
```python
def compute_altman_z_score(ticker, provider, as_of_date=None) -> tuple[float, dict]:
    # Z' = 6.56*(working_cap/assets) + 3.26*(retained_earnings/assets) 
    #     + 6.72*(ebit/assets) + 1.05*(book_equity/liabilities)
    # Z < 1.81 → distress zone → score -1.0
    # Z > 2.99 → safe zone → score +1.0
```
- **Commercial tag:** `{source: "wrds:comp.fundq", replacement: "FMP financial-scores or compute from FMP statements", cost: "$29/mo FMP Starter"}`

### Signal 2: FCF Yield Trend (cash burn detection)
```python
def compute_fcf_yield_trend(ticker, provider, as_of_date=None) -> tuple[float, dict]:
    # FCF = oancfy - capxy (operating CF minus capex)
    # Compare trailing 4 quarters: declining 3+ consecutive → strong short signal
```
- **Commercial tag:** `{source: "wrds:comp.fundq", replacement: "FMP cash-flow-statement quarterly", cost: "$29/mo FMP Starter"}`

### Signal 3: Sloan Accruals Ratio (earnings quality)
```python
def compute_accruals_score(ticker, provider, as_of_date=None) -> tuple[float, dict]:
    # Accrual ratio = (net_income - operating_CF) / avg(total_assets)
    # High accruals (>0.10) → earnings manipulation risk → short signal
    # Documented by Sloan (1996), IC ~0.03-0.06
```
- **Commercial tag:** `{source: "wrds:comp.fundq", replacement: "Computed from FMP income + cash flow statements", cost: "$29/mo FMP Starter"}`

### Asymmetric blending
In `blend_fundamentals_into_signals()`:
- **Long candidates** (composite > 0): quality score + IBES revision (existing)
- **Short candidates** (composite < 0): Altman Z + FCF trend + accruals (new signals target distress)

This mirrors the existing `sentiment_conflicts_short` asymmetric logic.

---

## Phase 5: Short Signal Validation (Medium)

**Depends on:** Phase 4
**Deliverable:** Evidence-based answer on whether fundamental signals improve short selection

### Tests to run
1. **Baseline**: Shorts ON, no fundamentals (already measured: 26% win rate, -2.73% avg)
2. **+ Quality score**: Shorts ON, balance sheet quality overlay
3. **+ IBES revision**: Shorts ON, analyst revision overlay  
4. **+ Both**: Shorts ON, quality + revision overlay
5. **Each at multiple weights**: 0.05, 0.10, 0.15, 0.20

### Extended validation
- Run from **2013-01-01** (not 2020) for statistical power — 20+ walk-forward windows
- Break down short performance by:
  - Fundamental signal strength (strong bearish vs mild bearish)
  - Market regime (VIX high vs low)
  - Sector
  - Holding period

### Decision gate
If short win rate improves to >40% AND average short P&L turns positive, recommend enabling shorts with fundamental gate. Otherwise, shorts stay disabled and fundamentals remain long-only overlay.

---

## Phase 6: LLM Agent Enhancement (Small)

**Depends on:** Phase 3
**Deliverable:** Agents receive point-in-time fundamentals for live analysis

### Modify
- `quant/fundamentals.py` `load_cached_fundamentals()` — add `wrds_store` parameter. When available, pull from WRDS store with `as_of_date=today` for live use. Otherwise fall back to FMP cache (existing behavior).
- `agents/earnings.py` — no changes needed (already consumes `cached_fundamentals` dict)
- `agents/risk.py` — no changes needed
- `orchestrator.py` `prepare_data()` — try WRDS store first, fall back to FMP cache

---

## Risk Log

| Risk | Mitigation |
|------|-----------|
| WRDS subscription doesn't include IBES | Check access in Phase 1 with `db.list_tables(library='ibes')`. If missing, Phase 4 uses Compustat EPS trend as proxy. |
| Identifier mapping gaps (ticker ↔ gvkey ↔ IBES ticker) | Map through CUSIP (8-digit), not ticker string. Both CRSP and IBES have CUSIP fields. Ticker reuse and non-standard symbols make direct matching unreliable. |
| `rdq` NULL contamination (~15% of records, especially pre-2010) | Fall back to `datadate + 45 days`. Tag imputed rows with `rdq_inferred=True`. Optionally exclude from short validation via `require_rdq=True` query param. |
| Compustat `oancfy` is YTD, not quarterly | Difference consecutive quarters during ETL: `ocf_q = oancfy_t - oancfy_{t-1}` (reset at fiscal year start when `fqtr=1`). |
| WRDS connection drops during large pulls | Save raw pulls as parquet to `~/.wrds_cache/`. seed_wrds.py checks for existing parquet before re-pulling. |
| Commercial migration difficulty | Tags travel with data. The hardest replacements are `rdq` (no FMP equivalent for exact report date) and IBES `anndats` (no retail API has per-analyst estimate history). These are flagged in the tags. |
| Backtest results change after fix | Expected — the snapshot results had lookahead bias. Document before/after Sharpe for transparency. |
| Survivorship bias in universe | Current S&P 500 list only has current members. WRDS has historical membership via `comp.idxcst_his`. Pull in Phase 5 when scaling beyond liquid_50. |
| Academic license breach | Add startup guard: if `WRDS_ACADEMIC_LICENSE=true` (default) and `ENV=production`, raise `EnvironmentError`. Enforced in wrds_client.py. |
| Two call sites in backtest.py (lines ~1705 and ~2095) | Extract overlay application into `_apply_fundamental_overlay(signals, reb_date, config)` before modifying, so there is only one call site to maintain. |
| WRDS flags default OFF | `enable_wrds_fundamentals` defaults to `False` — never active unless explicitly requested. Prevents accidental Sharpe regression. |

---

## Execution Order

```
Phase 1 (connection)     ← START HERE
    ↓
Phase 2 (store + ETL)
    ↓
Phase 3 (provider + backtest) → Phase 6 (LLM agents, parallel)
    ↓
Phase 4 (IBES signal)
    ↓
Phase 5 (short validation) ← DECISION GATE
```

Phases 3 and 6 can run in parallel. Phase 5 is the payoff — everything before it is infrastructure.

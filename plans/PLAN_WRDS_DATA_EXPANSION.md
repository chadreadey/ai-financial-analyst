# WRDS Data Expansion Plan

**Date:** 2026-04-07
**Context:** S&P 500 seeded with Compustat + IBES (25K + 150K + 25K rows). This plan covers the next data pulls after earnings signals are validated.

---

## Currently Seeded

| Dataset | Table | Rows | Signals Built |
|---------|-------|------|---------------|
| Compustat Quarterly | `comp.fundq` | 25,170 | Quality score, SUE, fundamental overlays |
| IBES Consensus | `ibes.statsumu_epsus` | 150,185 | ERM (earnings revision momentum), analyst dispersion |
| IBES Actuals | `ibes.actu_epsus` | 24,925 | SUE (standardized unexpected earnings) |
| Fama-French | `ff.fivefactors_daily` | 15,770 | Factor attribution |
| CRSP Link | `crsp.ccmxpf_linktable` | — | Identifier crosswalk |

---

## Tier 1: Pull After Earnings Signals Validated

### 1. 13F Institutional Holdings
- **Table:** `tr_13f.s34` (125M rows)
- **What:** Every institutional investor's quarterly equity positions (SEC 13F filings)
- **Signal:** Smart money flow — compute quarterly change in institutional ownership per stock. Stocks where institutions accumulate outperform (Yan & Zhang 2009, JFE). Independent of price and earnings signals.
- **Fields needed:** `mgrno` (manager ID), `cusip`, `shares`, `prc`, `rdate` (report date), `fdate` (filing date)
- **Point-in-time key:** `fdate` (filing date, typically 45 days after quarter end)
- **Size estimate for S&P 500:** ~2-3M rows (500 stocks × ~500 institutions × ~13 years × 4 quarters)
- **Commercial tag:** `{source: "wrds:tr_13f.s34", replacement: "SEC EDGAR 13F XML parsing (free but requires infrastructure) or WhaleWisdom API ($50/mo)", cost: "$0-50/mo"}`
- **Implementation:** Medium. Need to aggregate from institution-level to stock-level: `Δ_ownership = sum(shares_t) - sum(shares_{t-1})` across all institutions per stock.

### 2. Capital IQ Key Developments
- **Table:** `ciq_keydev.ciqkeydev` (34M rows)
- **What:** Structured corporate events — M&A, guidance changes, management changes, debt issuance, restructurings, regulatory actions
- **Use:** Feed as structured context to LLM agents (EarningsAgent, RiskAgent, CompetitiveAgent). Replace unstructured news scraping with categorized events.
- **Fields needed:** `companyid`, `keydevid`, `keydevtypeid` (event type), `headline`, `situation`, `announcedate`, `entereddate`
- **Key event types:** Guidance (raised/lowered/initiated), M&A (acquirer/target), Executive changes, Restructuring, Dividend changes
- **Point-in-time key:** `announcedate`
- **Commercial tag:** `{source: "wrds:ciq_keydev", replacement: "S&P Capital IQ Pro ($15K+/yr) or manual news parsing", cost: "$15K+/yr"}`
- **Implementation:** Medium. Need entity mapping (CIQ companyid → ticker). Events are pre-categorized, so agent context is rich.
- **Agent integration:** Add `ciq_events` enrichment section to AnalysisData. EarningsAgent sees guidance changes. RiskAgent sees restructurings. CompetitiveAgent sees M&A.

### 3. CRSP Daily Returns
- **Table:** `crsp.dsf_v2` (110M rows)
- **What:** Daily stock returns, split-adjusted, delisting-adjusted
- **Signals:** 
  - Idiosyncratic volatility (Ang et al. 2006) — regress daily returns on FF3, keep residual std. Documented alpha, survives FF5.
  - Short-term reversal (1-month) — for weekly or daily strategies (not currently relevant for monthly)
  - Proper delisting-adjusted backtest returns
- **Fields needed:** `permno`, `date`, `ret`, `prc`, `vol`, `shrout`, `dlret` (delisting return)
- **Size estimate for S&P 500:** ~15M rows (500 stocks × ~3200 trading days × ~13 years) — large but manageable
- **Commercial tag:** `{source: "wrds:crsp.dsf_v2", replacement: "Already have Alpaca/Tiingo for prices. Delisting adjustment is the unique value.", cost: "$0"}`
- **Implementation:** Easy for IVOL signal (daily regression per stock per month). Large data pull — consider downloading to parquet rather than SQLite.

---

## Tier 2: Pull for AI Agent Enrichment

### 4. SEC Filing Analytics
- **Table:** `wrdssec_all.dforms` (43M rows) + related tables
- **What:** Filing metadata — form types, filing dates, acceptance dates, document counts
- **Use:** Track filing patterns as risk signals. Late filings, NT filings (notification of late filing), restatements. Feed to RiskAgent.
- **Signal:** Companies that file late or restate have documented negative future returns.
- **Commercial tag:** `{source: "wrds:wrdssec_all", replacement: "SEC EDGAR XBRL API (free) + custom parsing", cost: "$0 but significant dev effort"}`
- **Implementation:** Easy to pull metadata. Hard to extract text content.

### 5. Executive Compensation
- **Table:** `comp_execucomp.anncomp` (374K rows)
- **What:** CEO/CFO base salary, bonus, stock awards, option grants, total compensation
- **Use:** Alignment signal — high stock-based comp relative to cash = management aligned with shareholders. Excessive total comp relative to peers = governance concern.
- **Agent integration:** DCFAgent (management incentive analysis), RiskAgent (governance risk)
- **Commercial tag:** `{source: "wrds:comp_execucomp", replacement: "Publicly available in proxy statements but unstructured. ExecPay API for structured data.", cost: "$0-200/yr"}`
- **Implementation:** Easy. Simple annual data per executive.

### 6. ISS Governance Scores
- **Table:** `risk_governance.gset` (14K rows)
- **What:** Board independence, dual-class structure, poison pills, audit committee quality
- **Use:** Governance quality filter — avoid companies with poor governance. Feed to RiskAgent.
- **Academic evidence:** Gompers, Ishii, Metrick (2003) "Corporate Governance and Equity Prices" — G-index predicts returns.
- **Commercial tag:** `{source: "wrds:risk_governance", replacement: "ISS Governance direct ($10K+/yr)", cost: "$10K+/yr"}`
- **Implementation:** Easy. Small dataset, annual frequency.

---

## Tier 3: Investigate Further

### 7. Revelio Workforce Data
- **Table:** `revelio.*` (32M rows across tables)
- **What:** Job postings, employee counts, turnover, hiring/firing by company and role
- **Use:** Leading indicator — mass hiring in engineering = growth investment. Mass layoffs = cost-cutting/distress. Role-level data (hiring ML engineers vs laying off sales) is extremely granular.
- **Agent integration:** CompetitiveAgent (workforce strategy), RiskAgent (operational health)
- **Status:** Need to explore table structure. Novel data source for LLM agents.

### 8. RavenPack News Sentiment
- **Tables:** `ravenpack_dj.*` (some tables accessible, some empty/restricted)
- **What:** NLP-scored news sentiment with event categorization, entity disambiguation, relevance scores
- **Use:** Replace Finnhub sentiment with institutional-grade. 150+ event types scored intraday.
- **Status:** Partial access — need to check which specific tables/time periods are available. Would be a major upgrade over Finnhub free tier.
- **Commercial tag:** `{source: "wrds:ravenpack_dj", replacement: "RavenPack Edge ($40K+/yr) or Finnhub Premium ($50/mo for degraded version)", cost: "$50-40K/yr"}`

---

## Pull Priority After Earnings Signal Validation

| Priority | Dataset | Why Now | Effort |
|----------|---------|---------|--------|
| **1** | 13F Holdings | Independent quant signal (smart money flow) | Medium |
| **2** | CIQ Key Developments | Biggest upgrade for LLM agent context | Medium |
| **3** | CRSP Daily | IVOL signal + delisting-adjusted returns | Easy (large data) |
| **4** | Executive Compensation | Agent context (small, easy win) | Easy |
| **5** | ISS Governance | Agent context (small, easy win) | Easy |
| **6** | Revelio Workforce | Novel alternative data, needs exploration | Medium |
| **7** | RavenPack | Assess access level first | Unknown |

---

## Scaling Notes

- Current `.wrds_pit.db` size: ~30MB (S&P 500, 13 years, Compustat + IBES)
- Adding 13F: +~50-100MB
- Adding CRSP daily: +~2GB → consider separate parquet files instead of SQLite
- Adding CIQ key dev: +~100MB
- Total estimated: ~2.5GB for full data stack

All WRDS data is academic-use only. Commercial replacement costs are documented per-dataset in the commercial tags table.

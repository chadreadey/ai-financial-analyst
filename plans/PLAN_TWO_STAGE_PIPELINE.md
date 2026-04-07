# Two-Stage Quant-LLM Pipeline: Architecture + Implementation Plan

## Architecture Decision

**Chosen: Two-Stage Pipeline with Phased Deployment (Architecture D from GAN analysis)**

The veto gate alone is too blunt — a single Risk agent can't rank replacements. The parallel one-shot is too shallow. The full two-stage pipeline focuses LLM spend on the decision boundary (stocks ranked 8-20 where quant scores cluster) and provides rich structured data for blending.

### Data Flow

```
MONTHLY REBALANCE
       │
       ▼
┌──────────────────────────┐
│  Quant Screen             │
│  50 stocks × 6 signals    │
│  + sentiment overlay      │
│  + regime filter          │
│  → ranked by composite    │
└────────┬─────────────────┘
         │ Top 20 candidates
         ▼
┌──────────────────────────┐
│  LLM Deep Analysis        │
│  BatchOrchestrator         │
│  20 stocks × 7 LLM calls  │
│  DeepSeek specialists      │
│  Claude synthesis          │
│  Concurrency: 4            │
│  ~4 min wall clock         │
└────────┬─────────────────┘
         │ LLM verdicts
         ▼
┌──────────────────────────┐
│  Score Blender             │
│  α=0.70 quant + 0.30 LLM  │
│  Conviction damping        │
│  Hard vetoes (SELL, risk≥8)│
│  Quant floor at 0.15       │
└────────┬─────────────────┘
         │ Blended scores
         ▼
┌──────────────────────────┐
│  Portfolio Construction    │
│  Sector cap (max 2-3)     │
│  Top 10 positions          │
│  Regime-adjusted sizing    │
└──────────────────────────┘
```

### Key Design Rules

1. **α = 0.70 (quant-dominant)** — quant has 6 years OOS validation, LLM has zero
2. **LLM agents do NOT see quant scores** — prevents rubber-stamping
3. **Conviction damping** — LLM scores below 0.30 conviction are damped toward zero
4. **Hard vetoes** — LLM SELL verdict or risk_score ≥ 8 vetoes quant longs
5. **Quant floor** — composite < 0.15 cannot be rescued by LLM
6. **Hybrid routing** — DeepSeek V3 for specialists, Claude for synthesis (75% cost savings)

### Cost

| Scale | Monthly Cost |
|---|---|
| 15 stocks (top N) | ~$1.39 |
| 20 stocks | ~$1.86 |
| Full universe fallback | Uses quant-only, $0 |

---

## Implementation Phases

### Phase 0: Config + Provider Factory (1-2 hrs)
**Files:** `config.py`, `llm/providers.py`
- Add DeepSeek settings: `deepseek_api_key`, `deepseek_base_url`, `deepseek_specialist_model`
- Add pipeline settings: `enable_llm_screen`, `llm_screen_top_n=20`, `llm_screen_alpha=0.70`, `llm_screen_concurrency=4`
- Add `get_provider_for_role(role)` factory: "specialist" → DeepSeek, "synthesis" → Anthropic
- Falls back gracefully if DEEPSEEK_API_KEY unset

### Phase 1: Headless Orchestrator (3-4 hrs)
**Files:** `orchestrator.py`, `prompts/synthesis.md`
- Add `run_headless(ticker, timeout=120) -> dict` method
- Reuses existing `prepare_data()` and agent pipeline
- Skips progress callbacks, paper trading, SSE streaming
- Returns: `{ticker, verdict, conviction_score, risk_score, weighted_score, raw_structured}`
- Extend synthesis prompt to emit `risk_score` (1-10) and `weighted_score` (0-1) in JSON block

### Phase 2: Score Blender (2-3 hrs)
**Files:** NEW `quant/score_blender.py`
- `LLMVerdict` and `BlendedScore` dataclasses
- `blend_scores()` function with α, conviction damping, hard vetoes
- Maps LLM weighted_score (0-1) → (-1, +1) to match quant composite scale
- Unit-testable standalone, no API calls needed

### Phase 3: BatchOrchestrator (4-6 hrs)
**Files:** NEW `quant/llm_screen.py`, modify `orchestrator.py`
- `BatchOrchestrator.run_batch(tickers) -> dict[str, LLMVerdict]`
- asyncio.Semaphore(4) for concurrency control
- Per-ticker timeout (120s), fallback to quant-only if >50% fail
- Add `specialist_provider` param to `Orchestrator.__init__` (backward-compatible)

### Phase 4: Backtest Integration (2 hrs)
**Files:** `quant/backtest.py`
- Add `_apply_llm_overlay()` following existing overlay pattern (mutates composite_score in place)
- Add optional `llm_scores` param to `build_target_portfolio()`
- Vetoed tickers naturally fall below long_threshold

### Phase 5: Pipeline Entry Point (4-5 hrs)
**Files:** NEW `quant/pipeline.py`, NEW `scripts/run_pipeline.py`
- `run_monthly_pipeline()` chains: quant screen → top N selection → LLM batch → blend → portfolio
- CLI: `python scripts/run_pipeline.py --universe liquid_50 --dry-run`
- Flags: `--top-n`, `--no-llm`, `--json`

### Phase 6: Shadow Tracker (3 hrs)
**Files:** NEW `quant/shadow_tracker.py`
- SQLite table logging quant-only vs blended picks per rebalance
- Tracks: veto hit rate, rank correlation, promotion accuracy
- `print_shadow_report()` for human review

### Phase 7: Promotion Gate (1-2 hrs)
**Files:** NEW `scripts/check_promotion_readiness.py`
- Three gates: veto hit rate > 60%, rank correlation < 0.90, minimum 12 runs
- Does NOT auto-enable — user sets `ENABLE_LLM_SCREEN=true` manually after review

---

## Validation Plan

**Phase A: Shadow Mode (Months 1-3)**
- Run both quant-only and blended portfolios
- Log all picks, vetoes, LLM verdicts to shadow tracker
- DO NOT trade on LLM signals

**Phase B: Conditional Deployment (Month 4+)**
- Deploy only if all three promotion gates pass
- Start with α=0.70, review quarterly

**Phase C: Alpha Tuning (Month 6+)**
- Sweep α ∈ {0.60, 0.70, 0.80} on quarterly basis
- Never optimize on fewer than 3 months of live data

---

## Implementation Order (with parallelism)

```
Week 1:  Phase 0 + Phase 2 (parallel, no API needed)
Week 1:  Phase 1 (requires one Claude call to verify)
Week 2:  Phase 3 (requires DeepSeek key)
Week 2:  Phase 4 (small, can parallel with Phase 3)
Week 3:  Phase 5 (integrates everything)
Week 3:  Phase 6 (shadow tracker)
Month 4: Phase 7 (after 3 months of shadow data)
```

**Total estimated effort: ~20-25 hours across 3 weeks**

---

## Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| DeepSeek API down | High | Per-ticker timeout + fallback to quant-only |
| LLM adds no value (efficient market for mega-caps) | Medium | Shadow mode validates before deployment |
| Score calibration drift (DeepSeek model updates) | Medium | Monthly score distribution monitoring |
| Synthesis prompt missing risk_score/weighted_score | High | Phase 1a explicitly adds before any batch run |
| asyncio.run() conflicts with FastAPI event loop | Medium | Pipeline runs from CLI only, not API routes |

---

## Files Inventory

### New Files (7)
- `quant/llm_screen.py` — BatchOrchestrator
- `quant/score_blender.py` — Blend logic + dataclasses
- `quant/pipeline.py` — Monthly pipeline orchestration
- `quant/shadow_tracker.py` — Validation logging
- `scripts/run_pipeline.py` — CLI entry point
- `scripts/check_promotion_readiness.py` — Promotion gate checker

### Modified Files (4)
- `orchestrator.py` — Add `run_headless()`, `specialist_provider` param
- `llm/providers.py` — Add `get_provider_for_role()` factory
- `config.py` — Add 10+ new settings fields
- `quant/backtest.py` — Add `_apply_llm_overlay()`, modify `build_target_portfolio()`

### Prompt Changes (1)
- `prompts/synthesis.md` — Add `risk_score` and `weighted_score` to JSON block

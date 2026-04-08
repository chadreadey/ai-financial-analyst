# Plans Index

**Last updated:** 2026-04-08

## Active Plans (by priority)

| Plan | Status | Completeness | Next Step |
|------|--------|-------------|-----------|
| [PLAN_ALPHA_EXPANSION](PLAN_ALPHA_EXPANSION.md) | **Master plan** | 10% | Complete Phase 0 (wire redundancy + CPCV + factor attribution) |
| [PLAN_SIGNAL_STRESS_TEST](PLAN_SIGNAL_STRESS_TEST.md) | Active | 40% | Build `quant/factor_attribution.py` (FF5+Mom regression) |
| [PLAN_WRDS_INTEGRATION](PLAN_WRDS_INTEGRATION.md) | Active | 60% | Build `wrds_client.py` + `wrds_puller.py` (Phase 1) |
| [PLAN_TRADINGAGENTS_IMPROVEMENTS](PLAN_TRADINGAGENTS_IMPROVEMENTS.md) | Active | 5% | Improvement 1: bull/bear debate prompt (quick win) |
| [PLAN_TWO_STAGE_PIPELINE](PLAN_TWO_STAGE_PIPELINE.md) | Active | 0% | Phase 0: config + headless orchestrator |
| [PLAN_WRDS_DATA_EXPANSION](PLAN_WRDS_DATA_EXPANSION.md) | Active | 5% | Tier 1: 13F institutional holdings |
| [PLAN_WRDS_RAG_SEEDING](PLAN_WRDS_RAG_SEEDING.md) | Active | 0% | Depends on WRDS Integration Phase 2 |
| [PLAN_GRAPHRAG](PLAN_GRAPHRAG.md) | Active | 0% | Phase 1: minimal viable graph |

## Completed Plans

| Plan | Completed | Summary |
|------|-----------|---------|
| [PLAN_SEMANTIC_LAYER](research/PLAN_SEMANTIC_LAYER.md) | 2026-04-08 | Canonical metrics, scoring constants, cache TTL, backend convergence, API schema validation |

## Reference

| File | Purpose |
|------|---------|
| [HANDOFF_20260407](HANDOFF_20260407.md) | Latest session summary — CPCV, WRDS, earnings signals findings |
| [research/](research/) | Literature reviews, cost analysis, gap analysis, completed plans |

## Research Documents

| File | Topic |
|------|-------|
| [RESEARCH_ALPHA_SIGNALS](research/RESEARCH_ALPHA_SIGNALS.md) | ERM/SUE/dispersion literature (drives earnings_signals.py) |
| [RESEARCH_SYSTEM_GAP_ANALYSIS](research/RESEARCH_SYSTEM_GAP_ANALYSIS.md) | System vs. 2024 literature audit — priority roadmap |
| [RESEARCH_PRE_EVENT_TRADING](research/RESEARCH_PRE_EVENT_TRADING.md) | Pre-FOMC/CPI/earnings drift signals |
| [RESEARCH_LLM_COSTS](research/RESEARCH_LLM_COSTS.md) | Token economics — hybrid DeepSeek+Claude strategy |
| [BURN_RATE](research/BURN_RATE.md) | API/LLM cost projections at scale |

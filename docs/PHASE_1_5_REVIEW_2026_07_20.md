---
title: Phase 1–5 Review — Agent-First PM Branch
date: 2026-07-20
branch: feat/agent-first-pm
author: session-artifact
---

# Phase 1–5 Review — feat/agent-first-pm

You asked to complete the remaining phases from `MEMO_2026_07_13_LEAN_QUANT_STRONG_AI`. Phase 0 (IC test) was already done in commit `060394f`. Phases 1–5 landed today in five commits on top of that.

## What's on the branch

| Commit | Phase | Summary |
|---|---|---|
| `18570d2` | Phase 1 | Screener composite (QMJ/SUE/ERM), IC-t-stat weights, candidate-list generator |
| `2e91390` | Phase 2 | Portfolio Construction agent + AI-augmented replay harness |
| `b8a1c3e` | Phase 3 | 3-series eval (SPY / Quant-only / AI-augmented) + attribution report |
| `fc5d690` | Phase 4 | XGBoost meta-model on AI picks (`beat_sector_21d` target) |
| `16ad834` | Phase 5 | Paper-sleeve scaffolding (IdeaCard schema + hard-cap position book) |

66 tests across 5 phases; full suite (excluding router tests) is 394/394 green.

## Files added

```
quant/screener.py                      Phase 1 — screener composite
quant/three_series_eval.py             Phase 3 — return-series builder + attribution
quant/ai_pick_meta_model.py            Phase 4 — XGBoost per-pick meta-model
agents/portfolio_construction.py       Phase 2 — PC agent (LLM + heuristic paths)
sleeve/idea_card.py                    Phase 5 — Pydantic IdeaCard / DeskAction
sleeve/paper_sleeve.py                 Phase 5 — paper position book with caps
scripts/generate_candidate_lists.py    Phase 1 — walk-forward candidate writer
scripts/generate_ai_augmented_picks.py Phase 2 — replay writer (heuristic|llm)
scripts/run_three_series_eval.py       Phase 3 — 3-series runner
scripts/train_ai_pick_meta.py          Phase 4 — meta-model training runner
tests/test_screener.py                 Phase 1 — 16 tests
tests/test_portfolio_construction.py   Phase 2 — 17 tests
tests/test_three_series_eval.py        Phase 3 — 12 tests
tests/test_ai_pick_meta_model.py       Phase 4 —  7 tests
tests/test_paper_sleeve.py             Phase 5 — 14 tests
```

## Artifacts generated

```
runs/candidates/YYYY-MM-DD.json        84 files: 2018-01 … 2024-12, top-50 per month
runs/ai_picks/YYYY-MM-DD.json          84 files (heuristic default; --mode llm supported)
docs/eval/three_series/latest.json     metrics + attribution snapshot
docs/eval/three_series/latest.md       human-readable report
docs/eval/three_series/daily_returns.csv  wide DataFrame for plotting
models/ai_pick_meta.pkl                trained meta-model
models/ai_pick_meta.pkl.metrics.json   train/test AUC, F1, base-rate
models/training_frame.csv              the 828-row training set
```

## Headline result (heuristic mode; do not over-interpret)

```
SPY:           Sharpe 0.75, ann 13.43%, MaxDD 33.7%
Quant-only:    Sharpe 0.99, ann 24.68%, MaxDD 35.4%
AI-augmented:  Sharpe 0.99, ann 24.68%, MaxDD 35.4%    (identical — heuristic PC ≡ quant)

ΔSharpe (AI − Quant) = 0.00 ← the honest baseline until --mode llm runs
```

Meta-model on 828 heuristic picks: train AUC 0.89 / test AUC 0.50 — features are all downstream of the composite the picks were made from, so there's no signal to learn. Both numbers become meaningful once LLM-mode picks diverge from the top-composite ordering.

## What to look at first

1. `docs/eval/three_series/latest.md` — the punchline in 12 lines.
2. `runs/candidates/2024-12-31.json` and `runs/ai_picks/2024-12-31.json` — see one rebalance end-to-end (composite → picks).
3. This file.
4. Any of the 5 test files — the tests are the tightest spec of each phase's contract.

## Known caveats / notes for the next session

- **Survivorship bias**: candidate lists were built from *today's* WRDS PIT universe, so pre-2024 rebalances get to know winners like APP / SMCI / AXON in advance. This is why total-return numbers are punchier than session-3 numbers. Filed for the next audit.
- **Heuristic PC ≡ Quant**: the phase-3 `Verdict` explicitly calls this out. Running `python3 scripts/generate_ai_augmented_picks.py --mode llm` will produce a genuine AI series; expect real LLM costs (84 calls at ~$0.03-0.05 each = ~$3-4 for Claude Sonnet 4.6).
- **Meta-model is a scaffold, not a signal**: with heuristic picks the meta-model has nothing to learn. Retrain after `--mode llm`.
- **Sleeve is paper-only, schema-only**: no broker integration, no LLM extractor. Ready for a future phase that wires IdeaCards from `warehouse/crown_briefings.py` into it.

## Follow-ups worth queuing

- Run `--mode llm` end-to-end for one recent 12-month window, retrain meta-model, re-run three-series eval to actually measure AI edge.
- Add a survivorship-adjustment (use point-in-time R1000 constituents) — moves the total-return numbers back to reality.
- Wire `warehouse/crown_briefings.py` extractor to produce IdeaCards and register them with the sleeve.
- Dashboard tab that consumes `docs/eval/three_series/latest.json` for a visual 3-series comparison.

## Test suite status

```
$ python -m pytest tests/ -q --ignore=tests/routers
394 passed, 1 warning in 36.16s
```

Green across every phase. No skipped tests introduced.

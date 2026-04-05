#!/usr/bin/env bash
# One-shot: run TimesFM overlay backtest after Tiingo rate limit resets.
set -euo pipefail
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
set -a && source .env && set +a

echo "=== $(date) — Starting TimesFM overlay backtest ==="

# A/B comparison: quant-only vs quant+TimesFM, liquid_10, 3 years
python scripts/run_timesfm_backtest.py \
  --universe liquid_10 \
  --start 2022-01-01 \
  --rebalance monthly \
  --timesfm-weight 0.15 \
  --output backtest_timesfm_comparison.json \
  2>&1 | tee /tmp/backtest_timesfm.log

echo ""
echo "=== $(date) — TimesFM backtest complete ==="

# Self-cleanup: remove the crontab entry
crontab -l 2>/dev/null | grep -v 'run_timesfm_backtest_cron' | crontab - 2>/dev/null || true

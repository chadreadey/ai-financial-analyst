#!/usr/bin/env bash
# One-shot: run both quant backtests after Tiingo rate limit resets.
set -euo pipefail
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
export PATH="/Users/chadreadey/opt/anaconda3/bin:$PATH"
set -a && source .env && set +a

echo "=== $(date) — Starting quant backtests ==="

echo "--- Backtest 1: liquid_10, 2022-01-01 ---"
python scripts/run_backtest.py --universe liquid_10 --start 2022-01-01 \
  --output backtest_liquid10_2022.json 2>&1 | tee /tmp/backtest_liquid10.log

echo ""
echo "--- Backtest 2: liquid_20, 2018-01-01, walk-forward ---"
python scripts/run_backtest.py --universe liquid_20 --start 2018-01-01 --walk-forward \
  --output backtest_liquid20_wf_2018.json 2>&1 | tee /tmp/backtest_liquid20_wf.log

echo ""
echo "=== $(date) — Both backtests complete ==="

# Self-cleanup: remove the crontab entry
crontab -l 2>/dev/null | grep -v 'run_both_backtests' | crontab - 2>/dev/null || true

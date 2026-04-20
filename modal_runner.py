"""
Modal backtest runner — executes experiments dispatched from the brain Telegram bot.
Codebase is cloned from GitHub so this works from Railway (no local mount needed).
"""
from __future__ import annotations
from typing import Optional
import modal

app = modal.App("ai-financial-analyst")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install([
        "pandas>=2.0.0",
        "numpy>=1.24.0",
        "scikit-learn>=1.3.0",
        "xgboost>=2.0.0",
        "scipy>=1.10",
        "requests>=2.25.0",
        "yfinance>=0.2.54",
        "filterpy>=1.4.5",
        "pykalman>=0.9.7",
        "statsmodels>=0.14.0",
        "anthropic>=0.40.0",
        "httpx>=0.27.0",
        "python-dotenv>=1.0.0",
        "fredapi>=0.5",
        "lxml>=4.9.0",
        "beautifulsoup4>=4.12.0",
    ])
    .run_commands(
        "git clone https://github.com/chadreadey/ai-financial-analyst.git /root/app"
    )
)

secrets = [modal.Secret.from_name("ai-financial-analyst-secrets")]

FALLBACK_TICKERS = ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","JPM","V","UNH","XOM","JNJ","PG","MA","HD","BAC"]


@app.function(
    image=image,
    secrets=secrets,
    timeout=600,
    cpu=4,
    memory=8192,
)
def run_backtest(
    tickers: str = "",
    start_date: str = "2020-01-01",
    end_date: str = "",
    train_months: int = 24,
    test_months: int = 6,
) -> dict:
    """Run a full walk-forward backtest and return metrics dict."""
    import sys
    import os
    sys.path.insert(0, "/root/app")

    from quant.backtest import BacktestConfig, run_walk_forward

    ticker_list = [t.strip() for t in tickers.split(",")] if tickers else FALLBACK_TICKERS
    config = BacktestConfig(
        tickers=ticker_list,
        start_date=start_date,
        end_date=end_date,
        train_months=train_months,
        test_months=test_months,
    )
    results = run_walk_forward(config)
    return _format_results(results)


@app.function(
    image=image,
    secrets=secrets,
    timeout=900,
    cpu=4,
    memory=8192,
)
def run_experiment(
    experiment_name: str,
    experiment_code: str,
    branch: str = "",
    baseline_metrics: Optional[dict] = None,
) -> dict:
    """
    Run an arbitrary experiment script and compare to baseline.
    experiment_code: Python code string to exec — must set results['metrics'] dict.
    """
    import sys
    import traceback
    sys.path.insert(0, "/root/app")

    namespace = {"results": {}}
    try:
        exec(experiment_code, namespace)
        metrics = namespace["results"].get("metrics", {})
    except Exception as e:
        return {
            "status": "error",
            "experiment": experiment_name,
            "error": traceback.format_exc(),
            "message": str(e),
        }

    gates = _check_gates(metrics, baseline_metrics or {})

    return {
        "status": "pass" if gates["all_pass"] else "fail",
        "experiment": experiment_name,
        "branch": branch,
        "metrics": metrics,
        "gates": gates,
        "summary": _format_summary(experiment_name, metrics, gates, baseline_metrics),
    }


@app.function(
    image=image,
    secrets=secrets,
    timeout=1200,
    cpu=8,
    memory=16384,
)
def run_cpcv(
    tickers: str = "",
    n_splits: int = 10,
    test_size: int = 63,
    n_test_groups: int = 2,
) -> dict:
    """Combinatorial Purged Cross-Validation. 8 CPUs, 16GB."""
    import sys
    sys.path.insert(0, "/root/app")

    from quant.cpcv import run_cpcv as _run_cpcv

    ticker_list = [t.strip() for t in tickers.split(",")] if tickers else FALLBACK_TICKERS
    results = _run_cpcv(
        tickers=ticker_list,
        n_splits=n_splits,
        test_size=test_size,
        n_test_groups=n_test_groups,
    )
    return results


def _check_gates(metrics: dict, baseline: dict) -> dict:
    gates = {}
    sharpe = metrics.get("sharpe_ratio", 0)
    base_sharpe = baseline.get("sharpe_ratio", 0.5)
    gates["sharpe_vs_baseline"] = sharpe >= base_sharpe
    gates["sharpe_positive"] = sharpe > 0
    ic = metrics.get("information_coefficient", metrics.get("ic", 0))
    gates["ic_positive"] = ic > 0
    max_dd = abs(metrics.get("max_drawdown", 1.0))
    gates["max_drawdown_ok"] = max_dd < 0.20
    alpha = metrics.get("alpha", metrics.get("annualized_alpha", 0))
    gates["alpha_positive"] = alpha > 0
    gates["all_pass"] = all(v for k, v in gates.items() if k != "all_pass")
    return gates


def _format_results(results) -> dict:
    if isinstance(results, dict):
        return results
    try:
        return {
            "sharpe_ratio": getattr(results, "sharpe_ratio", 0),
            "annualized_alpha": getattr(results, "annualized_alpha", 0),
            "max_drawdown": getattr(results, "max_drawdown", 0),
            "information_coefficient": getattr(results, "ic_mean", 0),
            "total_return": getattr(results, "total_return", 0),
        }
    except Exception:
        return {"raw": str(results)}


def _format_summary(name: str, metrics: dict, gates: dict, baseline: Optional[dict]) -> str:
    sharpe = metrics.get("sharpe_ratio", "n/a")
    alpha = metrics.get("annualized_alpha", metrics.get("alpha", "n/a"))
    dd = metrics.get("max_drawdown", "n/a")
    ic = metrics.get("information_coefficient", metrics.get("ic", "n/a"))

    status = "✅ PASS" if gates["all_pass"] else "❌ FAIL"
    lines = [
        f"*{name}* — {status}",
        f"Sharpe: {sharpe:.3f}" if isinstance(sharpe, float) else f"Sharpe: {sharpe}",
        f"Alpha: {alpha:.2%}" if isinstance(alpha, float) else f"Alpha: {alpha}",
        f"Max DD: {dd:.2%}" if isinstance(dd, float) else f"Max DD: {dd}",
        f"IC: {ic:.4f}" if isinstance(ic, float) else f"IC: {ic}",
    ]
    if baseline:
        base_sharpe = baseline.get("sharpe_ratio")
        if base_sharpe and isinstance(sharpe, float):
            lines.append(f"Δ Sharpe vs baseline: {sharpe - base_sharpe:+.3f}")

    gate_lines = [f"{'✅' if v else '❌'} {k}" for k, v in gates.items() if k != "all_pass"]
    lines += gate_lines
    merge = "\n\n*Merge recommendation:* ✅ Ready" if gates["all_pass"] else "\n\n*Merge recommendation:* ❌ Not ready"
    return "\n".join(lines) + merge

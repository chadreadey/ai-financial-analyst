"""
Fama-French Five-Factor + Momentum (FF5+Mom) alpha attribution.

Phase 0c of the Signal Stack Stress Test:
  - Downloads daily factor returns from Kenneth French Data Library
  - Runs OLS regression with Newey-West HAC standard errors
  - Tests whether backtest alpha survives factor-adjustment
  - Computes rolling 60-month window regressions

If alpha t-stat < 1.96 after FF5+Mom, the strategy's returns are fully
explained by known factor exposures and there is no genuine alpha.
"""

from __future__ import annotations

import logging
from io import BytesIO, StringIO
from typing import Optional
from urllib.request import urlopen
from zipfile import ZipFile

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.linear_model import OLS

logger = logging.getLogger(__name__)

# ── Download factor data from Kenneth French Data Library ──────────────

FF5_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOM_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"


def _download_french_zip(url: str) -> str:
    """Download and extract CSV from a French data library zip file."""
    response = urlopen(url)
    zf = ZipFile(BytesIO(response.read()))
    csv_name = zf.namelist()[0]
    return zf.open(csv_name).read().decode("utf-8")


def _parse_daily_factors(raw_csv: str) -> pd.DataFrame:
    """Parse daily factor CSV, handling the multi-section French format."""
    lines = raw_csv.strip().split("\n")

    # Find data start (first line starting with 8-digit date like 19260701)
    data_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[0].isdigit() and len(stripped.split(",")[0].strip()) == 8:
            data_start = i
            break

    if data_start is None:
        raise ValueError("Could not find data start in French CSV")

    # Find header line
    header_line = data_start - 1
    while header_line >= 0 and not lines[header_line].strip():
        header_line -= 1

    # Read data rows until blank line or non-numeric start
    data_lines = []
    for i in range(data_start, len(lines)):
        stripped = lines[i].strip()
        if not stripped or not stripped[0].isdigit():
            break
        data_lines.append(stripped)

    header = lines[header_line].strip()
    csv_text = header + "\n" + "\n".join(data_lines)
    df = pd.read_csv(StringIO(csv_text))

    first_col = df.columns[0]
    df = df.rename(columns={first_col: "date"})
    df["date"] = pd.to_datetime(df["date"].astype(str).str.strip(), format="%Y%m%d")
    df = df.set_index("date")
    df.columns = [c.strip() for c in df.columns]

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_french_factors(start_date: str = "2014-01-01") -> pd.DataFrame:
    """
    Download and merge FF5 + Momentum daily factors.

    Returns DataFrame with columns: Mkt-RF, SMB, HML, RMW, CMA, UMD, RF
    Values are in percentage points (e.g., 0.05 = 0.05%).
    """
    logger.info("Downloading Fama-French 5 Factors (daily)...")
    ff5 = _parse_daily_factors(_download_french_zip(FF5_URL))

    logger.info("Downloading Momentum Factor (daily)...")
    mom = _parse_daily_factors(_download_french_zip(MOM_URL))
    mom.columns = ["UMD" if "Mom" in c else c for c in mom.columns]

    factors = ff5.join(mom[["UMD"]], how="inner")
    factors = factors[factors.index >= pd.Timestamp(start_date)]

    logger.info(
        "Factors loaded: %d obs, %s to %s",
        len(factors),
        factors.index.min().date(),
        factors.index.max().date(),
    )
    return factors


# ── Core regression ────────────────────────────────────────────────────

FACTOR_COLS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "UMD"]


def run_ff5_momentum_regression(
    portfolio_daily_returns: pd.Series,
    factors_df: pd.DataFrame,
    risk_free_col: str = "RF",
) -> dict:
    """
    Run FF5 + Momentum OLS regression with Newey-West HAC standard errors.

    Parameters
    ----------
    portfolio_daily_returns : pd.Series
        Daily portfolio returns as percentages (matching French factor units).
        If your returns are decimal (0.001 = 0.1%), multiply by 100 first.
    factors_df : pd.DataFrame
        Must contain: Mkt-RF, SMB, HML, RMW, CMA, UMD, RF
    risk_free_col : str
        Column name for risk-free rate in factors_df

    Returns
    -------
    dict with keys: ols_model, nw_model, n_obs, max_lags, alpha_annual,
                    alpha_t, alpha_p, alpha_significant, summary_text
    """
    # Compute excess returns: portfolio return - risk-free rate
    data = pd.concat(
        [portfolio_daily_returns.rename("port_ret"), factors_df[FACTOR_COLS + [risk_free_col]]],
        axis=1,
    ).dropna()

    excess = data["port_ret"] - data[risk_free_col]
    X = sm.add_constant(data[FACTOR_COLS])

    # Align
    common = excess.index.intersection(X.index)
    excess = excess.loc[common]
    X = X.loc[common]

    if len(common) < 60:
        return {"error": f"Insufficient overlapping data: {len(common)} days (need 60+)"}

    # OLS fit
    model = OLS(excess, X).fit()

    # Newey-West HAC standard errors
    T = len(excess)
    max_lags = int(np.floor(4 * (T / 100) ** (2 / 9)))
    nw_model = OLS(excess, X).fit(cov_type="HAC", cov_kwds={"maxlags": max(1, max_lags)})

    # Alpha analysis
    alpha_daily = nw_model.params["const"]
    alpha_se = nw_model.bse["const"]
    alpha_t = nw_model.tvalues["const"]
    alpha_p = nw_model.pvalues["const"]
    alpha_annual = alpha_daily * 252
    alpha_ci = nw_model.conf_int().loc["const"]

    significant = alpha_p < 0.05

    # Build summary text
    lines = [
        "",
        "=" * 70,
        "  FF5 + MOMENTUM FACTOR ATTRIBUTION",
        "=" * 70,
        "",
        f"  Sample: {excess.index.min().date()} to {excess.index.max().date()}",
        f"  Observations: {T}",
        f"  Newey-West lags: {max_lags}",
        "",
        f"  {'':>12} {'Coef':>10} {'NW SE':>10} {'NW t':>10} {'NW p':>10}",
        f"  {'-' * 55}",
    ]

    for var in ["const"] + FACTOR_COLS:
        coef = nw_model.params[var]
        se = nw_model.bse[var]
        t = nw_model.tvalues[var]
        p = nw_model.pvalues[var]
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        label = "alpha" if var == "const" else var
        lines.append(f"  {label:>12} {coef:>10.4f} {se:>10.4f} {t:>10.2f} {p:>10.4f} {sig}")

    lines.extend([
        "",
        f"  R-squared:     {nw_model.rsquared:.4f}",
        f"  Adj R-squared: {nw_model.rsquared_adj:.4f}",
        "",
        "  ── Alpha Significance Test (95% CI) ──",
        "",
        f"  Daily alpha:      {alpha_daily:.4f}% (SE: {alpha_se:.4f}%)",
        f"  Annualized alpha: {alpha_annual:.2f}%",
        f"  Newey-West t-stat: {alpha_t:.4f}",
        f"  p-value: {alpha_p:.6f}",
        f"  95% CI (annual):  [{alpha_ci[0] * 252:.2f}%, {alpha_ci[1] * 252:.2f}%]",
        "",
    ])

    if significant:
        direction = "positive" if alpha_daily > 0 else "negative"
        lines.append(f"  >>> RESULT: Alpha IS significant at 95%. {direction.title()} {alpha_annual:.2f}%/yr")
        lines.append(f"      after controlling for market, size, value, profitability, investment, momentum.")
    else:
        lines.append(f"  >>> RESULT: Alpha is NOT significant at 95% (t={alpha_t:.2f}, p={alpha_p:.4f})")
        lines.append(f"      Returns are explained by the six factor exposures.")

    # Harvey-Liu-Zhu check
    if abs(alpha_t) < 3.0:
        lines.append(f"  >>> HLZ threshold: t={alpha_t:.2f} < 3.0 — fails multiple-testing adjustment.")
    else:
        lines.append(f"  >>> HLZ threshold: t={alpha_t:.2f} >= 3.0 — survives multiple-testing adjustment.")

    lines.extend(["", "=" * 70])

    summary = "\n".join(lines)

    return {
        "nw_model": nw_model,
        "ols_model": model,
        "n_obs": T,
        "max_lags": max_lags,
        "alpha_daily": round(float(alpha_daily), 6),
        "alpha_annual": round(float(alpha_annual), 4),
        "alpha_t": round(float(alpha_t), 4),
        "alpha_p": round(float(alpha_p), 6),
        "alpha_significant": significant,
        "alpha_ci_annual": [round(float(alpha_ci[0] * 252), 2), round(float(alpha_ci[1] * 252), 2)],
        "r_squared": round(float(nw_model.rsquared), 4),
        "factor_betas": {col: round(float(nw_model.params[col]), 4) for col in FACTOR_COLS},
        "factor_t_stats": {col: round(float(nw_model.tvalues[col]), 4) for col in FACTOR_COLS},
        "summary_text": summary,
    }


# ── Rolling regression ─────────────────────────────────────────────────

def rolling_factor_regression(
    portfolio_daily_returns: pd.Series,
    factors_df: pd.DataFrame,
    window_months: int = 60,
    risk_free_col: str = "RF",
) -> pd.DataFrame:
    """
    Rolling window FF5+Mom regression using monthly resampled data.

    Returns DataFrame with rolling alpha, t-stat, and factor betas.
    """
    data = pd.concat(
        [portfolio_daily_returns.rename("port_ret"), factors_df[FACTOR_COLS + [risk_free_col]]],
        axis=1,
    ).dropna()

    excess = data["port_ret"] - data[risk_free_col]
    factor_data = data[FACTOR_COLS]

    # Resample to monthly (sum daily returns within each month)
    monthly_excess = excess.resample("ME").sum()
    monthly_factors = factor_data.resample("ME").sum()
    monthly = pd.concat([monthly_excess, monthly_factors], axis=1).dropna()

    results_list = []
    for i in range(window_months, len(monthly) + 1):
        window = monthly.iloc[i - window_months : i]
        y = window.iloc[:, 0]
        X = sm.add_constant(window[FACTOR_COLS])

        try:
            max_lags = max(1, int(np.floor(4 * (len(y) / 100) ** (2 / 9))))
            model = OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": max_lags})

            row = {
                "date": window.index[-1],
                "alpha_monthly": float(model.params["const"]),
                "alpha_t": float(model.tvalues["const"]),
                "alpha_p": float(model.pvalues["const"]),
                "alpha_annual": float(model.params["const"] * 12),
                "r_squared": float(model.rsquared),
            }
            for fc in FACTOR_COLS:
                row[f"beta_{fc}"] = float(model.params[fc])
                row[f"t_{fc}"] = float(model.tvalues[fc])

            results_list.append(row)
        except Exception:
            continue

    if not results_list:
        return pd.DataFrame()

    return pd.DataFrame(results_list).set_index("date")


# ── Convenience: extract daily returns from backtest equity curve ──────

def equity_curve_to_daily_returns(equity_curve: list[dict]) -> pd.Series:
    """
    Convert backtest equity_curve list to daily return series in percentage
    points (matching French factor units: 0.05 = 0.05%).

    equity_curve entries have {"date": "YYYY-MM-DD", "value": float}
    """
    df = pd.DataFrame(equity_curve)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # equity_curve entries use "equity" key (from backtest.py)
    col = "equity" if "equity" in df.columns else "value"

    # Daily returns as percentage points (to match French factors)
    returns = df[col].pct_change().dropna() * 100.0
    return returns


# ── Print rolling summary ──────────────────────────────────────────────

def print_rolling_summary(rolling_df: pd.DataFrame) -> str:
    """Format rolling regression summary."""
    if rolling_df.empty:
        return "  No rolling windows computed (insufficient data for 60-month windows)."

    lines = [
        "",
        "=" * 70,
        "  ROLLING 60-MONTH FF5+MOM REGRESSION",
        "=" * 70,
        "",
        f"  Windows computed: {len(rolling_df)}",
        f"  Period: {rolling_df.index.min().date()} to {rolling_df.index.max().date()}",
        "",
        "  Annualized Alpha Summary:",
        f"    Mean:   {rolling_df['alpha_annual'].mean():+.2f}%",
        f"    Median: {rolling_df['alpha_annual'].median():+.2f}%",
        f"    Min:    {rolling_df['alpha_annual'].min():+.2f}%",
        f"    Max:    {rolling_df['alpha_annual'].max():+.2f}%",
        "",
        f"  Windows with significant alpha (p<0.05): "
        f"{(rolling_df['alpha_p'] < 0.05).sum()} / {len(rolling_df)} "
        f"({(rolling_df['alpha_p'] < 0.05).mean() * 100:.0f}%)",
        "",
    ]

    # Show latest 5 windows
    lines.append("  Latest 5 windows:")
    lines.append(f"  {'Date':>12s} {'Alpha%':>8s} {'t-stat':>8s} {'p-val':>8s} {'R²':>6s}")
    lines.append(f"  {'-' * 48}")
    for _, row in rolling_df.tail(5).iterrows():
        sig = "*" if row["alpha_p"] < 0.05 else ""
        lines.append(
            f"  {row.name.strftime('%Y-%m'):>12s} {row['alpha_annual']:>+8.2f} "
            f"{row['alpha_t']:>8.2f} {row['alpha_p']:>8.4f} {row['r_squared']:>6.3f} {sig}"
        )

    lines.extend(["", "=" * 70])
    return "\n".join(lines)

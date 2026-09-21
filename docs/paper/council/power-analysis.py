#!/usr/bin/env python3
"""Measure sigma_e and the implied MDE for the contamination DiD.

Answers the question both the Prosecution and the Referee named as their
verdict-flipping condition, from data already committed to this repo.
Stdlib only -- no pandas required.

    python3 docs/paper/council/power-analysis.py
"""

import csv
import math
from collections import defaultdict

CSV = "docs/eval/three_series_llm/daily_returns.csv"


def mean(x):
    return sum(x) / len(x)


def sd(x):
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def corr(x, y):
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den


def main():
    rows = list(csv.DictReader(open(CSV)))
    date_col = list(rows[0].keys())[0]

    ai, det, dates = [], [], []
    for r in rows:
        try:
            a, b = float(r["AI-augmented"]), float(r["Quant-only"])
        except (TypeError, ValueError):
            continue
        ai.append(a)
        det.append(b)
        dates.append(r[date_col])

    print(f"n daily = {len(ai)}   {dates[0]} -> {dates[-1]}")
    print(f"daily rho(AI, DET) = {corr(ai, det):.4f}")

    # compound daily returns within each calendar month
    buckets = defaultdict(lambda: [1.0, 1.0])
    for d, a, b in zip(dates, ai, det):
        k = d[:7]
        buckets[k][0] *= 1 + a
        buckets[k][1] *= 1 + b

    keys = sorted(buckets)
    m_ai = [buckets[k][0] - 1 for k in keys]
    m_det = [buckets[k][1] - 1 for k in keys]
    e = [a - b for a, b in zip(m_ai, m_det)]

    sigma_e = sd(e) * 100
    em = mean(e)
    lag1 = sum((e[i] - em) * (e[i + 1] - em) for i in range(len(e) - 1)) / sum(
        (v - em) ** 2 for v in e
    )
    vol_ai = sd(m_ai) * math.sqrt(12) * 100

    print(f"\n=== MONTHLY (n={len(e)}) ===")
    print(f"rho(AI, DET)      = {corr(m_ai, m_det):.4f}")
    print(f"sigma_e           = {sigma_e:.3f} %/month")
    print(f"lag-1 autocorr(e) = {lag1:+.3f}")
    print(f"mean(e)           = {em * 100:+.3f} %/month "
          f"(naive t = {em / (sd(e) / math.sqrt(len(e))):+.2f})")
    print(f"AI annualized vol = {vol_ai:.2f} %")

    # SE(beta) under two-way FE, computed at sigma_e = 2.5 %/mo for a panel of
    # M models with cutoffs evenly spread over D straddling months, then
    # rescaled to the measured sigma_e.
    print("\n=== MDE_80 at the measured sigma_e ===")
    print(f"{'M':>3} {'D':>4} {'SE %/mo':>9} {'MDE %/mo':>10} {'MDE Sharpe':>11}")
    for M, D, se_at_2p5 in [(6, 24, 0.74), (8, 30, 0.57), (12, 36, 0.42), (20, 36, 0.32)]:
        se = se_at_2p5 * (sigma_e / 2.5)
        mde = 2.8 * se
        print(f"{M:>3} {D:>4} {se:>9.3f} {mde:>10.3f} {mde * 12 / vol_ai:>11.3f}")

    print("\nRange the abstract says readers need distinguished: 0.05 - 0.8 Sharpe")


if __name__ == "__main__":
    main()

# IC significance re-judgment (overlap-honest)

Source: `docs/audit/2026-08-25-rejudge/ic-results.json`  |  MBB resamples: 4000

## Horizon 1M (overlap 1)

| signal | n | mean IC | naive t | HAC t | IC lag-1 ρ | MBB p | old verdict | new verdict |
|---|---|---|---|---|---|---|---|---|
| analyst_dispersion | 120 | -0.0017 | -0.13 | -0.15 | +0.01 | 0.890 | DROP | **NO_SIGNAL** |
| erm | 120 | +0.0144 | +1.45 | +1.59 | -0.06 | 0.111 | MARGINAL | **MARGINAL** |
| hml_bm | 120 | -0.0059 | -0.46 | -0.43 | +0.07 | 0.659 | DROP | **NO_SIGNAL** |
| insider_mspr | 120 | -0.0085 | -1.11 | -1.19 | -0.13 | 0.229 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| institutional_flow | 120 | +0.0010 | +0.06 | +0.06 | +0.18 | 0.951 | DROP | **NO_SIGNAL** |
| obv_trend | 120 | -0.0081 | -0.66 | -0.64 | +0.03 | 0.524 | DROP | **NO_SIGNAL** |
| piotroski | 120 | +0.0003 | +0.04 | +0.04 | -0.01 | 0.965 | DROP | **NO_SIGNAL** |
| price_momentum | 118 | +0.0033 | +0.17 | +0.21 | -0.11 | 0.848 | DROP | **NO_SIGNAL** |
| qmj | 120 | +0.0245 | +2.81 | +2.64 | +0.03 | 0.007 | KEEP | **SIGNIFICANT** |
| quality_score | 120 | +0.0191 | +1.96 | +1.88 | +0.11 | 0.058 | MARGINAL | **MARGINAL** |
| sue | 120 | +0.0179 | +2.04 | +2.00 | -0.01 | 0.036 | KEEP | **SIGNIFICANT** |

## Horizon 3M (overlap 3)

| signal | n | mean IC | naive t | HAC t | IC lag-1 ρ | MBB p | old verdict | new verdict |
|---|---|---|---|---|---|---|---|---|
| analyst_dispersion | 120 | -0.0088 | -0.70 | -0.46 | +0.62 | 0.661 | DROP | **NO_SIGNAL** |
| erm | 120 | +0.0209 | +2.27 | +1.53 | +0.60 | 0.128 | KEEP | **MARGINAL** |
| hml_bm | 120 | -0.0107 | -0.78 | -0.48 | +0.71 | 0.635 | DROP | **NO_SIGNAL** |
| insider_mspr | 120 | -0.0150 | -1.89 | -1.25 | +0.53 | 0.226 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| institutional_flow | 120 | +0.0016 | +0.10 | +0.07 | +0.60 | 0.955 | DROP | **NO_SIGNAL** |
| obv_trend | 120 | -0.0096 | -0.85 | -0.90 | +0.03 | 0.350 | DROP | **NO_SIGNAL** |
| piotroski | 120 | -0.0133 | -1.83 | -1.23 | +0.56 | 0.237 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| price_momentum | 118 | -0.0001 | -0.01 | -0.00 | +0.62 | 0.998 | DROP | **NO_SIGNAL** |
| qmj | 120 | +0.0203 | +2.12 | +1.25 | +0.72 | 0.242 | KEEP | **NO_SIGNAL** |
| quality_score | 120 | +0.0194 | +1.70 | +1.04 | +0.72 | 0.316 | MARGINAL | **NO_SIGNAL** |
| sue | 120 | +0.0133 | +1.45 | +0.84 | +0.73 | 0.418 | MARGINAL | **NO_SIGNAL** |

## Horizon 6M (overlap 6)

| signal | n | mean IC | naive t | HAC t | IC lag-1 ρ | MBB p | old verdict | new verdict |
|---|---|---|---|---|---|---|---|---|
| analyst_dispersion | 120 | -0.0181 | -1.38 | -0.69 | +0.82 | 0.561 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| erm | 120 | +0.0263 | +2.53 | +1.39 | +0.77 | 0.155 | KEEP | **NO_SIGNAL** |
| hml_bm | 120 | -0.0147 | -1.01 | -0.51 | +0.84 | 0.637 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| insider_mspr | 120 | -0.0166 | -1.91 | -0.99 | +0.78 | 0.386 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| institutional_flow | 120 | +0.0095 | +0.67 | +0.35 | +0.76 | 0.773 | DROP | **NO_SIGNAL** |
| obv_trend | 120 | +0.0032 | +0.28 | +0.34 | -0.05 | 0.697 | DROP | **NO_SIGNAL** |
| piotroski | 120 | -0.0215 | -2.86 | -1.50 | +0.77 | 0.205 | KEEP_WRONG_SIGN | **NO_SIGNAL** |
| price_momentum | 118 | +0.0023 | +0.13 | +0.07 | +0.82 | 0.958 | DROP | **NO_SIGNAL** |
| qmj | 120 | +0.0183 | +1.80 | +0.95 | +0.82 | 0.287 | MARGINAL | **NO_SIGNAL** |
| quality_score | 120 | +0.0130 | +1.12 | +0.57 | +0.86 | 0.576 | MARGINAL | **NO_SIGNAL** |
| sue | 120 | +0.0069 | +0.67 | +0.34 | +0.83 | 0.764 | DROP | **NO_SIGNAL** |

## Horizon 12M (overlap 12)

| signal | n | mean IC | naive t | HAC t | IC lag-1 ρ | MBB p | old verdict | new verdict |
|---|---|---|---|---|---|---|---|---|
| analyst_dispersion | 120 | -0.0170 | -1.19 | -0.47 | +0.90 | 0.635 | MARGINAL_WRONG_SIGN | **NO_SIGNAL** |
| erm | 120 | +0.0118 | +1.11 | +0.67 | +0.78 | 0.449 | MARGINAL | **NO_SIGNAL** |
| hml_bm | 120 | -0.0093 | -0.62 | -0.23 | +0.91 | 0.848 | DROP | **NO_SIGNAL** |
| insider_mspr | 120 | -0.0279 | -2.97 | -1.19 | +0.83 | 0.286 | KEEP_WRONG_SIGN | **NO_SIGNAL** |
| institutional_flow | 120 | -0.0051 | -0.34 | -0.13 | +0.81 | 0.923 | DROP | **NO_SIGNAL** |
| obv_trend | 120 | -0.0010 | -0.09 | -0.11 | -0.06 | 0.931 | DROP | **NO_SIGNAL** |
| piotroski | 120 | -0.0336 | -5.28 | -2.14 | +0.80 | 0.099 | KEEP_WRONG_SIGN | **MARGINAL_WRONG_SIGN** |
| price_momentum | 118 | -0.0115 | -0.70 | -0.29 | +0.85 | 0.770 | DROP | **NO_SIGNAL** |
| qmj | 120 | +0.0188 | +2.60 | +1.19 | +0.80 | 0.200 | KEEP | **NO_SIGNAL** |
| quality_score | 120 | +0.0168 | +1.51 | +0.56 | +0.90 | 0.654 | MARGINAL | **NO_SIGNAL** |
| sue | 120 | +0.0050 | +0.56 | +0.21 | +0.87 | 0.856 | DROP | **NO_SIGNAL** |

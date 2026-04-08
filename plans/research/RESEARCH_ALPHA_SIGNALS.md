# Alpha Signal Literature Review

**Date:** 2026-04-07
**Goal:** Find signals independent of FF5+Mom for monthly-rebalanced equity portfolio
**Context:** Current system has zero factor-adjusted alpha (t=1.08). Need genuinely independent signals.

---

## Ranked Recommendations

### Tier 1: IMPLEMENT (strong evidence, independent of FF5)

**1. Earnings Revision Momentum (ERM)** — #1 priority
- **Paper:** Novy-Marx (2015), "Fundamentally, Momentum is Fundamental Momentum", NBER WP 20984
- **Definition:** `ERM = (MeanEst_t - MeanEst_{t-3}) / |MeanEst_{t-3}|` using IBES FY1 consensus
- **IC:** 0.04-0.08 monthly
- **FF5+Mom alpha:** SURVIVES. Novy-Marx proves earnings momentum subsumes price momentum, not vice versa.
- **WRDS:** `ibes.statsumu_epsus` (meanest, statpers, fpedats), `ibes.detu_epsus` for detail
- **Implementation:** Medium
- **Key insight:** This is the "real" momentum signal. SMA trend is a crude proxy; ERM is the source.

**2. Standardized Unexpected Earnings (SUE)** — #2 priority  
- **Paper:** Bernard & Thomas (1989), "Post-Earnings-Announcement Drift", JAR
- **Definition:** `SUE = (EPS_q - EPS_{q-4}) / std(EPS_q - EPS_{q-4})` over 8 quarters
- **IC:** ~0.03-0.06 monthly, top-bottom decile spread ~4%/quarter
- **FF5+Mom alpha:** Partially survives. Has attenuated post-publication but residual exists.
- **WRDS:** `comp.fundq` (epspiq, rdq), `ibes.actu_epsus`
- **Implementation:** Easy
- **Key insight:** Complements ERM — ERM captures pre-announcement revisions, SUE captures post-announcement drift. Together they cover the full earnings cycle.

**3. Analyst Dispersion (negative signal)** — #3 priority
- **Paper:** Diether, Malloy, Scherbina (2002), "Differences of Opinion", JF
- **Definition:** `Dispersion = std(analyst EPS estimates) / |mean(analyst EPS estimates)|`
- **FF5+Mom alpha:** Partially survives. Different mechanism (disagreement/short constraints).
- **WRDS:** `ibes.statsumu_epsus` (stdev, numest, meanest)
- **Implementation:** Easy (free with IBES data already loaded for ERM)

### Tier 2: CONSIDER (some independent alpha, worth testing)

**4. Idiosyncratic Volatility** — Ang et al. (2006), JF. Survives FF5+Mom. Monthly from daily returns. Use as filter (exclude high IVOL) not scoring signal. Requires `crsp.dsf`.

**5. Net Stock Issuance** — Pontiff & Woodgate (2008), JF. Some residual beyond FF5 but small in value-weighted. Easy from `crsp.msf` (shrout).

### Tier 3: DO NOT IMPLEMENT (subsumed by FF5)

- **Gross Profitability** — IS the RMW factor. Novy-Marx (2013) led to FF5 including RMW.
- **Accruals Anomaly** — Subsumed by CMA. Strategy already has CMA loading of -0.20.
- **Asset Growth** — IS the CMA factor. Directly redundant.
- **PEAD** — Fully overlaps with SUE.
- **Short Interest** — Value-weighted alpha insignificant.
- **Insider Sentiment** — Small-cap concentrated, modest after adjustment.

---

## Key Insight

The existing 5 technical signals have zero cross-sectional IC at monthly frequency because they are price-pattern signals operating at the wrong timescale. Earnings-based signals (ERM, SUE) operate on fundamentally different information and have documented monthly IC that survives factor adjustment. This is where the independent alpha lives.

**ERM is the single most important signal to add.** It is the "real" momentum factor that price momentum approximates.

---

## Sources
- Novy-Marx (2015): https://mysimon.rochester.edu/novy-marx/research/FMFM.pdf
- Bernard & Thomas (1989): JAR 27, 1-36
- Diether, Malloy, Scherbina (2002): JF 57(5), 2113-2141
- Ang, Hodrick, Xing, Zhang (2006): JF 61(1), 259-299
- Guerard, Rachev, Shao (2013): Journal of Investing
- Pontiff & Woodgate (2008): JF 63(2), 921-945
- Sloan (1996): TAR 71, 289-315 (accruals — subsumed by CMA)
- Cooper, Gulen, Schill (2008): JF 63(4), 1609-1651 (asset growth — IS CMA)
- Novy-Marx (2013): JFE 108(1), 1-28 (gross profitability — IS RMW)

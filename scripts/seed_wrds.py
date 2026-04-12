#!/usr/bin/env python3
"""
WRDS Data Seed Script.

One-time ETL: pulls Compustat quarterly, IBES consensus + actuals,
and CRSP-Compustat-IBES identifier links into the local SQLite store.

Usage:
    python scripts/seed_wrds.py --tickers AAPL,MSFT,GOOGL
    python scripts/seed_wrds.py --universe liquid_10
    python scripts/seed_wrds.py --universe liquid_50 --start-year 2013
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import wrds

from quant.wrds_store import WRDSPointInTimeStore
from quant.universe import get_universe


def progress(msg):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")


def build_ticker_links(db, tickers):
    """
    Build ticker → gvkey → permno → ibes_ticker crosswalk.

    Strategy: go through Compustat tic → gvkey, then CRSP link for permno,
    then IBES id for ibes_ticker via CUSIP matching.
    """
    progress(f"Building identifier crosswalk for {len(tickers)} tickers...")

    tic_list = ",".join(f"'{t}'" for t in tickers)

    # Step 1: Compustat tic → gvkey + cusip
    comp_ids = db.raw_sql(f"""
        SELECT DISTINCT tic AS ticker, gvkey, cusip
        FROM comp.security
        WHERE tic IN ({tic_list})
    """)

    if comp_ids.empty:
        # Try company table as fallback
        comp_ids = db.raw_sql(f"""
            SELECT DISTINCT tic AS ticker, gvkey, cusip
            FROM comp.company
            WHERE tic IN ({tic_list})
        """)

    progress(f"  Compustat: {len(comp_ids)} ticker-gvkey mappings")

    # Step 2: CRSP link: gvkey → permno
    gvkey_list = ",".join(f"'{g}'" for g in comp_ids["gvkey"].unique())
    crsp_links = db.raw_sql(f"""
        SELECT gvkey, lpermno AS permno, linkdt AS link_start, linkenddt AS link_end
        FROM crsp.ccmxpf_linktable
        WHERE gvkey IN ({gvkey_list})
          AND linktype IN ('LU', 'LC')
          AND linkprim IN ('P', 'C')
        ORDER BY gvkey, linkdt DESC
    """)
    progress(f"  CRSP links: {len(crsp_links)} gvkey-permno mappings")

    # Step 3: IBES ticker via CUSIP (first 8 chars)
    cusip8_list = ",".join(
        f"'{c[:8]}'" for c in comp_ids["cusip"].dropna().unique() if len(c) >= 8
    )
    ibes_ids = pd.DataFrame()
    if cusip8_list:
        ibes_ids = db.raw_sql(f"""
            SELECT DISTINCT ticker AS ibes_ticker, cusip AS ibes_cusip
            FROM ibes.id
            WHERE cusip IN ({cusip8_list})
        """)
    progress(f"  IBES: {len(ibes_ids)} cusip-ibes_ticker mappings")

    # Merge everything
    links = comp_ids.copy()
    links["cusip8"] = links["cusip"].str[:8]

    # Add CRSP permno (take most recent link per gvkey)
    crsp_dedup = crsp_links.drop_duplicates(subset="gvkey", keep="first")
    links = links.merge(crsp_dedup[["gvkey", "permno", "link_start", "link_end"]],
                        on="gvkey", how="left")

    # Add IBES ticker via CUSIP
    if not ibes_ids.empty:
        ibes_ids["cusip8"] = ibes_ids["ibes_cusip"].str[:8]
        ibes_dedup = ibes_ids.drop_duplicates(subset="cusip8", keep="first")
        links = links.merge(ibes_dedup[["cusip8", "ibes_ticker"]], on="cusip8", how="left")
    else:
        links["ibes_ticker"] = None

    # Fill missing link dates
    links["link_start"] = links["link_start"].fillna("1900-01-01")
    links["link_end"] = links["link_end"].fillna("2099-12-31")

    progress(f"  Final crosswalk: {len(links)} rows, "
             f"{links['ibes_ticker'].notna().sum()} have IBES mapping")

    # Report unmapped tickers
    unmapped = links[links["ibes_ticker"].isna()]["ticker"].unique()
    if len(unmapped) > 0:
        progress(f"  ⚠ No IBES mapping: {', '.join(unmapped)}")

    return links


def pull_compustat(db, gvkeys, start_year):
    """Pull Compustat quarterly fundamentals."""
    gvkey_list = ",".join(f"'{g}'" for g in gvkeys)
    progress(f"Pulling Compustat quarterly for {len(gvkeys)} gvkeys from {start_year}...")

    df = db.raw_sql(f"""
        SELECT gvkey, tic, datadate, rdq, fyearq, fqtr,
               atq, ceqq, ltq, dlcq, dlttq, cheq, actq, lctq,
               saleq, revtq, niq, ibq, oancfy, epsfxq, epspiq, capxy,
               cogsq, xsgaq, cshoq
        FROM comp.fundq
        WHERE gvkey IN ({gvkey_list})
          AND fyearq >= {start_year}
          AND indfmt = 'INDL'
          AND datafmt = 'STD'
          AND popsrc = 'D'
          AND consol = 'C'
        ORDER BY gvkey, datadate
    """)

    rdq_null = df["rdq"].isna().sum()
    progress(f"  Pulled {len(df)} rows, {rdq_null} with NULL rdq ({rdq_null/len(df)*100:.1f}%)")
    return df


def pull_ibes_consensus(db, ibes_tickers, start_year):
    """Pull IBES monthly consensus summary (unadjusted)."""
    if not ibes_tickers:
        progress("  No IBES tickers — skipping consensus pull")
        return pd.DataFrame()

    tic_list = ",".join(f"'{t}'" for t in ibes_tickers)
    progress(f"Pulling IBES consensus for {len(ibes_tickers)} tickers from {start_year}...")

    df = db.raw_sql(f"""
        SELECT ticker, statpers, fpedats, fpi,
               meanest, medest, stdev, numest, numup, numdown
        FROM ibes.statsumu_epsus
        WHERE ticker IN ({tic_list})
          AND statpers >= '{start_year}-01-01'
          AND measure = 'EPS'
          AND fpi IN ('1', '2')
        ORDER BY ticker, statpers
    """)

    progress(f"  Pulled {len(df)} consensus rows")
    return df


def pull_ibes_actuals(db, ibes_tickers, start_year):
    """Pull IBES actual EPS (unadjusted, quarterly)."""
    if not ibes_tickers:
        progress("  No IBES tickers — skipping actuals pull")
        return pd.DataFrame()

    tic_list = ",".join(f"'{t}'" for t in ibes_tickers)
    progress(f"Pulling IBES actuals for {len(ibes_tickers)} tickers from {start_year}...")

    df = db.raw_sql(f"""
        SELECT ticker, pends, anndats, value, pdicity
        FROM ibes.actu_epsus
        WHERE ticker IN ({tic_list})
          AND pends >= '{start_year}-01-01'
          AND measure = 'EPS'
          AND pdicity = 'QTR'
        ORDER BY ticker, pends
    """)

    progress(f"  Pulled {len(df)} actuals rows")
    return df


def pull_13f_holdings(db, tickers, start_year):
    """
    Pull aggregated 13F institutional holdings per ticker per quarter.

    Uses tr_13f.s34 — Thomson Reuters 13F dataset. Aggregates position-level
    data into per-ticker quarterly summaries: holder count, total shares,
    buyers/sellers.
    """
    tic_list = ",".join(f"'{t}'" for t in tickers)
    progress(f"Pulling 13F institutional holdings for {len(tickers)} tickers from {start_year}...")

    df = db.raw_sql(f"""
        SELECT ticker, rdate,
               COUNT(DISTINCT mgrno) AS n_holders,
               SUM(shares) AS total_shares,
               SUM(CASE WHEN change > 0 THEN 1 ELSE 0 END) AS n_buying,
               SUM(CASE WHEN change < 0 THEN 1 ELSE 0 END) AS n_selling,
               SUM(CASE WHEN change = 0 OR change IS NULL THEN 1 ELSE 0 END) AS n_unchanged
        FROM tr_13f.s34
        WHERE ticker IN ({tic_list})
          AND rdate >= '{start_year}-01-01'
        GROUP BY ticker, rdate
        ORDER BY ticker, rdate
    """)

    progress(f"  Pulled {len(df)} ticker-quarter rows "
             f"({df['ticker'].nunique()} tickers, "
             f"{df['rdate'].nunique()} quarters)")
    return df


def main():
    parser = argparse.ArgumentParser(description="Seed WRDS point-in-time store")
    parser.add_argument("--universe", default="",
                        help="Universe: liquid_10/20/50 (default: use --tickers)")
    parser.add_argument("--tickers", default="",
                        help="Comma-separated tickers")
    parser.add_argument("--start-year", type=int, default=2013,
                        help="Start year for data pull (default: 2013)")
    parser.add_argument("--db-path", default="",
                        help="Path to SQLite store (default: .wrds_pit.db)")
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    elif args.universe:
        tickers = get_universe(args.universe)
    else:
        print("ERROR: provide --universe or --tickers")
        sys.exit(1)

    print(f"\nWRDS Seed: {len(tickers)} tickers, start year {args.start_year}")
    print(f"Tickers: {', '.join(tickers)}")

    store = WRDSPointInTimeStore(args.db_path)
    t0 = time.time()

    # Connect to WRDS
    progress("Connecting to WRDS...")
    db = wrds.Connection()

    # Step 1: Build identifier crosswalk
    links = build_ticker_links(db, tickers)
    n_links = store.ingest_ticker_links(links)
    progress(f"Ingested {n_links} ticker links")

    # Step 2: Pull Compustat quarterly
    gvkeys = links["gvkey"].dropna().unique()
    comp_df = pull_compustat(db, gvkeys, args.start_year)

    # Map gvkey → ticker for rows missing tic
    gvkey_to_ticker = dict(zip(links["gvkey"], links["ticker"]))
    comp_df["tic"] = comp_df.apply(
        lambda r: r["tic"] if pd.notna(r["tic"]) else gvkey_to_ticker.get(r["gvkey"], ""),
        axis=1,
    )
    n_comp = store.ingest_compustat(comp_df)
    progress(f"Ingested {n_comp} Compustat quarterly rows")

    # Step 3: Pull IBES consensus
    ibes_tickers = links["ibes_ticker"].dropna().unique().tolist()
    ibes_df = pull_ibes_consensus(db, ibes_tickers, args.start_year)
    n_ibes = store.ingest_ibes_consensus(ibes_df)
    progress(f"Ingested {n_ibes} IBES consensus rows")

    # Step 4: Pull IBES actuals
    actuals_df = pull_ibes_actuals(db, ibes_tickers, args.start_year)
    n_actuals = store.ingest_ibes_actuals(actuals_df)
    progress(f"Ingested {n_actuals} IBES actuals rows")

    # Step 5: Pull 13F institutional holdings
    inst_df = pull_13f_holdings(db, tickers, args.start_year)
    n_inst = store.ingest_inst_holdings(inst_df)
    progress(f"Ingested {n_inst} institutional holdings rows")

    # Step 6: Save commercial tags
    store.save_commercial_tags()

    db.close()
    elapsed = time.time() - t0

    # Summary
    summary = store.summary()
    print(f"\n{'=' * 60}")
    print(f"  WRDS SEED COMPLETE ({elapsed:.1f}s)")
    print(f"{'=' * 60}")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

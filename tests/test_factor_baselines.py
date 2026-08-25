"""
Smoke tests for `quant.factor_baselines`.

Tests run only if `.wrds_pit.db` is available (the WRDS PIT cache).
Marked with `pytest.mark.skipif` so CI doesn't blow up when the cache
is absent.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

WRDS_DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    ".wrds_pit.db",
)
WRDS_AVAILABLE = os.path.exists(WRDS_DB_PATH)
pytestmark = pytest.mark.skipif(
    not WRDS_AVAILABLE, reason="WRDS PIT cache (.wrds_pit.db) not present"
)


@pytest.fixture(scope="module")
def wrds_store():
    from quant.wrds_store import WRDSPointInTimeStore

    return WRDSPointInTimeStore()


@pytest.fixture(scope="module")
def first_known_ticker(wrds_store):
    """A ticker that we know has data in the WRDS cache."""
    import sqlite3

    conn = sqlite3.connect(wrds_store._db_path)
    row = conn.execute(
        "SELECT ticker FROM compustat_quarterly "
        "GROUP BY ticker HAVING COUNT(*) >= 6 ORDER BY ticker LIMIT 1"
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ── Piotroski ───────────────────────────────────────────────────────────


def test_piotroski_in_range(wrds_store, first_known_ticker):
    """F-score must always be in [0, 9]."""
    from quant.factor_baselines import compute_piotroski_score

    if first_known_ticker is None:
        pytest.skip("no ticker with sufficient quarters in cache")

    score = compute_piotroski_score(
        first_known_ticker,
        date(2022, 6, 30),
        wrds_store,
    )
    assert score is None or (isinstance(score, int) and 0 <= score <= 9)


def test_piotroski_pit_filtering_returns_none_before_first_filing(
    wrds_store,
    first_known_ticker,
):
    """Querying for an as_of_date before any filing must return None.

    This proves PIT discipline: data we don't have YET should not leak in.
    """
    from quant.factor_baselines import compute_piotroski_score

    if first_known_ticker is None:
        pytest.skip("no ticker with sufficient quarters in cache")

    # Date before any data exists in the cache (cache starts ~2012-09)
    score = compute_piotroski_score(
        first_known_ticker,
        date(2000, 1, 1),
        wrds_store,
    )
    assert score is None


def test_piotroski_typical_known_case(wrds_store):
    """Check at least one large-cap on a date we expect to score."""
    from quant.factor_baselines import compute_piotroski_score

    # AAPL is in the Dow / S&P, almost certainly in any WRDS cache that
    # has S&P 500-class names. Skip if not present.
    score = compute_piotroski_score("AAPL", date(2022, 12, 31), wrds_store)
    if score is None:
        pytest.skip("AAPL not in cache or insufficient data on test date")
    assert 0 <= score <= 9


# ── QMJ ─────────────────────────────────────────────────────────────────


def test_qmj_returns_float_or_none(wrds_store, first_known_ticker):
    from quant.factor_baselines import compute_qmj_score

    if first_known_ticker is None:
        pytest.skip("no ticker with sufficient quarters in cache")

    score = compute_qmj_score(
        first_known_ticker,
        date(2022, 6, 30),
        wrds_store,
    )
    assert score is None or isinstance(score, float)


def test_qmj_pit_filtering(wrds_store, first_known_ticker):
    from quant.factor_baselines import compute_qmj_score

    if first_known_ticker is None:
        pytest.skip("no ticker with sufficient quarters in cache")
    assert (
        compute_qmj_score(
            first_known_ticker,
            date(2000, 1, 1),
            wrds_store,
        )
        is None
    )


# ── HML ─────────────────────────────────────────────────────────────────


def test_hml_returns_none_without_price(wrds_store, first_known_ticker):
    """HML requires price to compute book/market — None price => None."""
    from quant.factor_baselines import compute_hml_score

    if first_known_ticker is None:
        pytest.skip("no ticker with sufficient quarters in cache")
    score = compute_hml_score(
        first_known_ticker,
        date(2022, 6, 30),
        wrds_store,
        price=None,
    )
    assert score is None


def test_hml_with_synthetic_price(wrds_store, first_known_ticker):
    from quant.factor_baselines import compute_hml_score

    if first_known_ticker is None:
        pytest.skip("no ticker with sufficient quarters in cache")
    score = compute_hml_score(
        first_known_ticker,
        date(2022, 6, 30),
        wrds_store,
        price=100.0,
    )
    # Either None (data missing for that ticker/date) or a positive ratio
    assert score is None or score > 0

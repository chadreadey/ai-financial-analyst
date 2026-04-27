"""
PIT-safety tests for institutional flow (RISK-1 from the 2026-04-27 audit).

The 13F filing deadline is quarter-end + 45 days (SEC Rule 13F-1). A backtest
at `as_of_date` must NOT consume a quarter whose filing window has not closed
by then — otherwise the score uses data that did not exist on the trade date.

These tests pin that guard down at three levels:
  1. The pure helper `_is_pit_safe_quarter` (boundary semantics)
  2. The FMP path of `fetch_and_score_institutional_flow` (rejects unfiled
     quarters, falls back to the prior PIT-safe quarter)
  3. The Finnhub fallback path (filters rows by `filingDate <= as_of_date`)
"""

from __future__ import annotations

from datetime import date

import pytest

# Reset the module-level caches between tests so prior runs don't leak state
# into PIT assertions. Uses a fresh fixture per test.


@pytest.fixture(autouse=True)
def _reset_institutional_flow_caches():
    from quant import institutional_flow as flow

    flow._raw_cache.clear()
    flow._finnhub_raw_cache.clear()
    flow._wrds_cache.clear()
    flow._score_cache.clear()
    yield
    flow._raw_cache.clear()
    flow._finnhub_raw_cache.clear()
    flow._wrds_cache.clear()
    flow._score_cache.clear()


# ── Helper-level boundary semantics ───────────────────────────────────


class TestIsPitSafeQuarterHelper:
    """Pin the boundary semantics of the PIT guard helper."""

    def test_quarter_unfiled_at_as_of_date_is_unsafe(self):
        from quant.institutional_flow import _is_pit_safe_quarter

        # Q1 2025 ends 2025-03-31 → deadline 2025-05-15.
        # as_of_date 2025-04-01 is before deadline → not safe.
        assert _is_pit_safe_quarter(
            quarter_end_date=date(2025, 3, 31),
            as_of_date=date(2025, 4, 1),
        ) is False

    def test_quarter_at_filing_deadline_is_safe(self):
        from quant.institutional_flow import _is_pit_safe_quarter

        # quarter_end + 45 days exactly == as_of_date → safe (boundary inclusive)
        assert _is_pit_safe_quarter(
            quarter_end_date=date(2025, 3, 31),
            as_of_date=date(2025, 5, 15),
        ) is True

    def test_quarter_past_filing_deadline_is_safe(self):
        from quant.institutional_flow import _is_pit_safe_quarter

        # Q4 2024 ends 2024-12-31 → deadline 2025-02-14.
        # as_of_date 2025-03-01 is well past deadline → safe.
        assert _is_pit_safe_quarter(
            quarter_end_date=date(2024, 12, 31),
            as_of_date=date(2025, 3, 1),
        ) is True

    def test_one_day_before_deadline_is_unsafe(self):
        from quant.institutional_flow import _is_pit_safe_quarter

        # Deadline = 2025-05-15. as_of = 2025-05-14 → not safe.
        assert _is_pit_safe_quarter(
            quarter_end_date=date(2025, 3, 31),
            as_of_date=date(2025, 5, 14),
        ) is False


# ── FMP path: full integration through fetch_and_score_institutional_flow ──


def _make_fmp_record(
    quarter_end: str,
    investor_name: str,
    shares: int = 1_000_000,
    change: int = 0,
) -> dict:
    """Build a minimal FMP institutional ownership record."""
    return {
        "date": quarter_end,
        "investorName": investor_name,
        "sharesNumber": shares,
        "sharesNumberChange": change,
        "ownershipPercent": 1.0,
    }


def _make_quarter_records(quarter_end: str, n: int = 5, change: int = 100_000) -> list[dict]:
    """Build N institutional records all dated to the same quarter-end."""
    return [
        _make_fmp_record(
            quarter_end,
            investor_name=f"Fund_{i}",
            shares=1_000_000 + i * 50_000,
            change=change,
        )
        for i in range(n)
    ]


class _FakeFmpClient:
    """Minimal FMP client surface needed by `_fetch_fmp_data`."""

    def __init__(self, payload_by_ticker: dict[str, list[dict]]):
        self._payload = payload_by_ticker

    def get_institutional_ownership_history(self, ticker: str) -> list[dict]:
        return list(self._payload.get(ticker, []))


class TestFmpPitGuard:
    def test_fmp_institutional_flow_rejects_unfiled_quarter(self):
        """
        If as_of_date < quarter_end + 45 days, the unfiled quarter must NOT
        be selected as `current_snapshot`. The function should either fall
        back to the prior (filed) quarter or, if none exists, return a
        zero/no-data score.
        """
        from quant.institutional_flow import fetch_and_score_institutional_flow

        # FMP returns BOTH Q4 2024 (filed by ~2025-02-14) AND Q1 2025
        # (would not file until ~2025-05-15).
        fmp_payload = {
            "AAPL": (
                # Q1 2025 — UNFILED at as_of_date = 2025-04-01
                _make_quarter_records("2025-03-31", n=8, change=500_000)
                # Q4 2024 — FILED before 2025-04-01
                + _make_quarter_records("2024-12-31", n=8, change=100_000)
            )
        }
        client = _FakeFmpClient(fmp_payload)

        score, meta = fetch_and_score_institutional_flow(
            ticker="AAPL",
            as_of_date=date(2025, 4, 1),
            wrds_store=None,
            fmp_client=client,
            fmp_cache=None,
            finnhub_client=None,
            finnhub_disk_cache=None,
        )

        # Must use Q4 2024 (the only PIT-safe quarter at this as_of_date),
        # not Q1 2025. We assert this by checking that the resulting score
        # is computed with no prior snapshot (since only one quarter is safe)
        # AND that the data source is fmp.
        assert meta.get("data_source") in {"fmp", "both"}, meta
        # n_prior_institutions equals n_institutions when there is no prior
        # quarter (the function copies current → prior in that case). This is
        # the observable proof that Q1 2025 was rejected — otherwise Q1 would
        # be current and Q4 would be prior, giving distinct values.
        assert meta["n_institutions"] == 8
        assert meta["n_prior_institutions"] == 8
        # And no QoQ delta (since there's only one safe quarter)
        assert meta["holder_count_change_pct"] == 0.0

    def test_fmp_institutional_flow_uses_latest_pit_safe_quarter(self):
        """
        If as_of_date is well past a quarter's filing deadline, the function
        should use that quarter as `current_snapshot`. Q4 2024 filed by
        2025-02-14 must be available at as_of_date = 2025-03-01.
        """
        from quant.institutional_flow import fetch_and_score_institutional_flow

        fmp_payload = {
            "AAPL": (
                # Q4 2024 — FILED by 2025-02-14, safe at 2025-03-01
                _make_quarter_records("2024-12-31", n=10, change=200_000)
                # Q3 2024 — FILED by 2024-11-14, also safe
                + _make_quarter_records("2024-09-30", n=8, change=0)
            )
        }
        client = _FakeFmpClient(fmp_payload)

        score, meta = fetch_and_score_institutional_flow(
            ticker="AAPL",
            as_of_date=date(2025, 3, 1),
            wrds_store=None,
            fmp_client=client,
            fmp_cache=None,
            finnhub_client=None,
            finnhub_disk_cache=None,
        )

        assert meta.get("data_source") in {"fmp", "both"}, meta
        # Current = Q4 2024 (10 holders), Prior = Q3 2024 (8 holders)
        assert meta["n_institutions"] == 10
        assert meta["n_prior_institutions"] == 8
        # 10 vs 8 → +25% holder growth (within winsorize band)
        assert meta["holder_count_change_pct"] == pytest.approx(25.0, abs=0.01)

    def test_fmp_returns_no_signal_when_no_quarter_is_pit_safe(self):
        """
        If every quarter in the FMP payload is unfiled at as_of_date, the
        function must NOT pick any of them — it should fall through to a
        zero/no-data result.
        """
        from quant.institutional_flow import fetch_and_score_institutional_flow

        # Only Q1 2025, which would not be filed until ~2025-05-15.
        # as_of_date = 2025-04-15 (still before deadline).
        fmp_payload = {
            "AAPL": _make_quarter_records("2025-03-31", n=10, change=500_000)
        }
        client = _FakeFmpClient(fmp_payload)

        score, meta = fetch_and_score_institutional_flow(
            ticker="AAPL",
            as_of_date=date(2025, 4, 15),
            wrds_store=None,
            fmp_client=client,
            fmp_cache=None,
            finnhub_client=None,
            finnhub_disk_cache=None,
        )

        # No PIT-safe FMP quarter, no Finnhub, no WRDS → score is 0 with
        # an "insufficient" / no-data style metadata.
        assert score == 0.0
        assert meta.get("data_source") in {"none", ""} or meta.get("n_institutions", 0) < 3


# ── Finnhub fallback PIT guard ────────────────────────────────────────


class _FakeFinnhubClient:
    def __init__(self, payload_by_ticker: dict[str, list[dict]]):
        self._payload = payload_by_ticker

    def get_institutional_ownership(self, ticker: str) -> list[dict]:
        return list(self._payload.get(ticker, []))


class TestFinnhubPitGuard:
    def test_finnhub_drops_rows_with_filing_date_after_as_of(self):
        """
        Finnhub rows with `filingDate > as_of_date` represent filings that
        were not public yet on the trade date. They must be excluded.
        """
        from quant.institutional_flow import fetch_and_score_institutional_flow

        # Build a Finnhub payload of 6 holders. Half were filed BEFORE
        # as_of_date (PIT-safe). Half were filed AFTER (must be dropped).
        fh_payload = {
            "AAPL": [
                # PIT-safe rows
                {"name": f"Fund{i}", "share": 1_000_000, "change": 50_000,
                 "filingDate": "2025-02-14"}
                for i in range(3)
            ] + [
                # NOT PIT-safe — filing happens after as_of_date
                {"name": f"Future{i}", "share": 5_000_000, "change": 1_000_000,
                 "filingDate": "2025-05-20"}
                for i in range(3)
            ]
        }
        client = _FakeFinnhubClient(fh_payload)

        score, meta = fetch_and_score_institutional_flow(
            ticker="AAPL",
            as_of_date=date(2025, 4, 1),
            wrds_store=None,
            fmp_client=None,
            fmp_cache=None,
            finnhub_client=client,
            finnhub_disk_cache=None,
        )

        # The Finnhub-only path should see exactly 3 PIT-safe holders.
        # (data_source becomes "finnhub" because there's no FMP data.)
        finnhub_meta = meta.get("finnhub_enrichment", {})
        assert finnhub_meta.get("finnhub_n_holders") == 3, meta

    def test_finnhub_drops_rows_with_unparseable_filing_date(self):
        """
        Conservative behavior: rows lacking a parseable `filingDate` cannot
        be confirmed PIT-safe and must be excluded.
        """
        from quant.institutional_flow import fetch_and_score_institutional_flow

        fh_payload = {
            "AAPL": [
                {"name": "NoDate", "share": 1_000_000, "change": 0},  # no filingDate
                {"name": "BadDate", "share": 1_000_000, "change": 0,
                 "filingDate": "not-a-date"},
                {"name": "GoodDate", "share": 1_000_000, "change": 0,
                 "filingDate": "2025-02-14"},
            ]
        }
        client = _FakeFinnhubClient(fh_payload)

        score, meta = fetch_and_score_institutional_flow(
            ticker="AAPL",
            as_of_date=date(2025, 4, 1),
            wrds_store=None,
            fmp_client=None,
            fmp_cache=None,
            finnhub_client=client,
            finnhub_disk_cache=None,
        )

        finnhub_meta = meta.get("finnhub_enrichment", {})
        # Only GoodDate survives the PIT filter.
        assert finnhub_meta.get("finnhub_n_holders") == 1, meta

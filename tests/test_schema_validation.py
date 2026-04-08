"""Tests for API response schema validation across all data providers."""

from __future__ import annotations

import logging

import pytest

from tiingo_client import _REQUIRED_EOD_FIELDS, _validate_eod_bar
from price_provider import _REQUIRED_ALPACA_BAR_FIELDS, _validate_alpaca_bar
from fmp_client import (
    _REQUIRED_INCOME_FIELDS,
    _REQUIRED_BALANCE_FIELDS,
    _REQUIRED_ESTIMATE_FIELDS,
    _validate_fmp_record,
)
from finnhub_client import _REQUIRED_NEWS_FIELDS, _validate_news_item


# ── Tiingo EOD Bar ──────────────────────────────────────────────────────

class TestValidateEodBar:
    def _good_bar(self) -> dict:
        return {
            "date": "2024-01-15T00:00:00+00:00",
            "adjClose": 150.0,
            "adjHigh": 152.0,
            "adjLow": 148.0,
            "adjOpen": 149.0,
            "adjVolume": 1000000,
            "close": 150.0,
            "high": 152.0,
            "low": 148.0,
            "open": 149.0,
            "volume": 1000000,
        }

    def test_good_bar_no_warning(self, caplog):
        bar = self._good_bar()
        with caplog.at_level(logging.WARNING, logger="tiingo_client"):
            result = _validate_eod_bar(bar, "AAPL")
        assert result is bar
        assert "missing fields" not in caplog.text

    def test_missing_adjclose_warns(self, caplog):
        bar = self._good_bar()
        del bar["adjClose"]
        with caplog.at_level(logging.WARNING, logger="tiingo_client"):
            result = _validate_eod_bar(bar, "AAPL")
        assert result is bar
        assert "schema: eod_bar response for AAPL missing fields: adjClose" in caplog.text

    def test_missing_multiple_fields_warns(self, caplog):
        bar = {"date": "2024-01-15", "close": 150.0}
        with caplog.at_level(logging.WARNING, logger="tiingo_client"):
            _validate_eod_bar(bar, "MSFT")
        assert "schema: eod_bar response for MSFT missing fields:" in caplog.text
        for field in ("adjClose", "adjHigh", "adjLow", "adjOpen", "adjVolume"):
            assert field in caplog.text

    def test_missing_close_warns(self, caplog):
        bar = self._good_bar()
        del bar["close"]
        with caplog.at_level(logging.WARNING, logger="tiingo_client"):
            _validate_eod_bar(bar, "GOOG")
        assert "schema: eod_bar response for GOOG missing fields: close" in caplog.text

    def test_empty_bar_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="tiingo_client"):
            _validate_eod_bar({}, "TSLA")
        assert "missing fields" in caplog.text

    def test_returns_bar_unchanged(self):
        bar = self._good_bar()
        result = _validate_eod_bar(bar, "AAPL")
        assert result == self._good_bar()


# ── Alpaca Bar ──────────────────────────────────────────────────────────

class TestValidateAlpacaBar:
    def _good_bar(self) -> dict:
        return {"t": "2024-01-15T05:00:00Z", "o": 149.0, "h": 152.0, "l": 148.0, "c": 150.0, "v": 1000000}

    def test_good_bar_no_warning(self, caplog):
        bar = self._good_bar()
        with caplog.at_level(logging.WARNING, logger="price_provider"):
            result = _validate_alpaca_bar(bar, "AAPL")
        assert result is bar
        assert "missing fields" not in caplog.text

    def test_missing_close_warns(self, caplog):
        bar = self._good_bar()
        del bar["c"]
        with caplog.at_level(logging.WARNING, logger="price_provider"):
            _validate_alpaca_bar(bar, "AAPL")
        assert "schema: alpaca_bar response for AAPL missing fields: c" in caplog.text

    def test_empty_bar_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="price_provider"):
            _validate_alpaca_bar({}, "NVDA")
        assert "missing fields" in caplog.text

    def test_returns_bar_unchanged(self):
        bar = self._good_bar()
        result = _validate_alpaca_bar(bar, "AAPL")
        assert result is bar
        assert result == self._good_bar()


# ── FMP Income Statement ────────────────────────────────────────────────

class TestValidateFmpIncome:
    def _good_record(self) -> dict:
        return {
            "date": "2024-03-31",
            "symbol": "AAPL",
            "revenue": 94836000000,
            "netIncome": 23636000000,
            "eps": 1.53,
            "epsDil": 1.52,
            "grossProfit": 43000000000,
            "ebitda": 30000000000,
        }

    def test_good_record_no_warning(self, caplog):
        rec = self._good_record()
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            result = _validate_fmp_record(rec, _REQUIRED_INCOME_FIELDS, "income_statement", "AAPL")
        assert result is rec
        assert "missing fields" not in caplog.text

    def test_missing_revenue_warns(self, caplog):
        rec = self._good_record()
        del rec["revenue"]
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            _validate_fmp_record(rec, _REQUIRED_INCOME_FIELDS, "income_statement", "AAPL")
        assert "schema: income_statement response for AAPL missing fields: revenue" in caplog.text

    def test_missing_multiple_warns(self, caplog):
        rec = {"date": "2024-03-31", "symbol": "AAPL"}
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            _validate_fmp_record(rec, _REQUIRED_INCOME_FIELDS, "income_statement", "AAPL")
        assert "revenue" in caplog.text
        assert "netIncome" in caplog.text


# ── FMP Balance Sheet ───────────────────────────────────────────────────

class TestValidateFmpBalance:
    def _good_record(self) -> dict:
        return {
            "date": "2024-03-31",
            "symbol": "AAPL",
            "totalAssets": 352583000000,
            "totalStockholdersEquity": 74100000000,
            "totalCurrentAssets": 143566000000,
            "totalCurrentLiabilities": 133973000000,
            "totalDebt": 104590000000,
            "cashAndCashEquivalents": 29965000000,
        }

    def test_good_record_no_warning(self, caplog):
        rec = self._good_record()
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            result = _validate_fmp_record(rec, _REQUIRED_BALANCE_FIELDS, "balance_sheet", "AAPL")
        assert result is rec
        assert "missing fields" not in caplog.text

    def test_missing_totalassets_warns(self, caplog):
        rec = self._good_record()
        del rec["totalAssets"]
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            _validate_fmp_record(rec, _REQUIRED_BALANCE_FIELDS, "balance_sheet", "MSFT")
        assert "schema: balance_sheet response for MSFT missing fields: totalAssets" in caplog.text


# ── FMP Analyst Estimates ───────────────────────────────────────────────

class TestValidateFmpEstimates:
    def test_good_record_no_warning(self, caplog):
        rec = {"date": "2025-01-01", "epsAvg": 6.70, "revenueAvg": 400000000000}
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            result = _validate_fmp_record(rec, _REQUIRED_ESTIMATE_FIELDS, "analyst_estimates", "AAPL")
        assert result is rec
        assert "missing fields" not in caplog.text

    def test_missing_epsavg_warns(self, caplog):
        rec = {"date": "2025-01-01", "revenueAvg": 400000000000}
        with caplog.at_level(logging.WARNING, logger="fmp_client"):
            _validate_fmp_record(rec, _REQUIRED_ESTIMATE_FIELDS, "analyst_estimates", "GOOG")
        assert "schema: analyst_estimates response for GOOG missing fields: epsAvg" in caplog.text


# ── Finnhub News ────────────────────────────────────────────────────────

class TestValidateNewsItem:
    def _good_item(self) -> dict:
        return {
            "id": 123456,
            "category": "company",
            "datetime": 1705334400,
            "headline": "Apple Reports Record Q1 Revenue",
            "summary": "Apple Inc. reported quarterly revenue of $119.6 billion.",
            "source": "Reuters",
            "url": "https://example.com/article",
            "related": "AAPL",
        }

    def test_good_item_no_warning(self, caplog):
        item = self._good_item()
        with caplog.at_level(logging.WARNING, logger="finnhub_client"):
            result = _validate_news_item(item, "AAPL")
        assert result is item
        assert "missing fields" not in caplog.text

    def test_missing_headline_warns(self, caplog):
        item = self._good_item()
        del item["headline"]
        with caplog.at_level(logging.WARNING, logger="finnhub_client"):
            _validate_news_item(item, "AAPL")
        assert "schema: news_item response for AAPL missing fields: headline" in caplog.text

    def test_missing_datetime_warns(self, caplog):
        item = self._good_item()
        del item["datetime"]
        with caplog.at_level(logging.WARNING, logger="finnhub_client"):
            _validate_news_item(item, "TSLA")
        assert "schema: news_item response for TSLA missing fields: datetime" in caplog.text

    def test_missing_all_required_warns(self, caplog):
        item = {"id": 123, "url": "https://example.com"}
        with caplog.at_level(logging.WARNING, logger="finnhub_client"):
            _validate_news_item(item, "META")
        assert "headline" in caplog.text
        assert "datetime" in caplog.text
        assert "source" in caplog.text

    def test_returns_item_unchanged(self):
        item = self._good_item()
        result = _validate_news_item(item, "AAPL")
        assert result == self._good_item()

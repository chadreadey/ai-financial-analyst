"""
SEC EDGAR API client with rate limiting and caching.

Key endpoints used:
  - Company tickers map  : https://www.sec.gov/files/company_tickers.json
  - Submissions (filings): https://data.sec.gov/submissions/CIK{cik}.json
  - Company facts (XBRL) : https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json

SEC requires:
  - A descriptive User-Agent header
  - Max 10 requests / second

When ENABLE_EDGARTOOLS is set, edgartools is used as a parallel enrichment
path for filing section extraction and financial data gap-filling.
"""

import os
import time
from typing import Any, Dict, List, Optional

import requests

from sec.cache import SECCache
from utils import env_flag

# Set edgartools identity on import (must happen before any edgartools calls)
_edgar_identity = os.getenv(
    "EDGAR_IDENTITY",
    os.getenv("SEC_USER_AGENT", "AIFinancialAnalyst admin@example.com"),
)
try:
    from edgar import set_identity
    set_identity(_edgar_identity)
except Exception:
    pass


BASE_URL = "https://data.sec.gov"
SEC_WWW = "https://www.sec.gov"
RATE_LIMIT_INTERVAL = 0.12  # ~8 req/s to stay safely under 10/s


class SECClient:
    """Synchronous SEC EDGAR API client with built-in rate limiting + caching."""

    def __init__(
        self,
        user_agent: str = "AIFinancialAnalyst admin@example.com",
        cache: Optional[SECCache] = None,
    ):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )
        self.cache = cache or SECCache()
        self._last_request_time: float = 0.0
        self._ticker_map: Optional[Dict[str, Dict]] = None

    # ── rate limiting ──────────────────────────────────────────────

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str) -> Any:
        self._throttle()
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.json()

    def _get_text(self, url: str) -> str:
        self._throttle()
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp.text

    # ── ticker → CIK resolution ───────────────────────────────────

    def _load_ticker_map(self) -> Dict[str, Dict]:
        """Load the SEC ticker→CIK mapping (cached)."""
        if self._ticker_map is not None:
            return self._ticker_map

        cached = self.cache.get("meta", "ticker_map")
        if cached is not None:
            self._ticker_map = cached
            return cached

        url = f"{SEC_WWW}/files/company_tickers.json"
        data = self._get(url)

        # Build a dict keyed by uppercase ticker
        ticker_map: Dict[str, Dict] = {}
        for entry in data.values():
            ticker_map[entry["ticker"].upper()] = {
                "cik": entry["cik_str"],
                "name": entry["title"],
            }

        self._ticker_map = ticker_map
        self.cache.set("meta", "ticker_map", ticker_map, ttl=86400 * 7)
        return ticker_map

    def resolve_ticker(self, ticker: str) -> Dict[str, Any]:
        """
        Return {"cik": str, "cik_padded": str, "name": str} for a ticker.
        Raises ValueError if ticker not found.
        """
        ticker_map = self._load_ticker_map()
        entry = ticker_map.get(ticker.upper())
        if entry is None:
            raise ValueError(
                f"Ticker '{ticker}' not found in SEC database. "
                "Check spelling or try the full company name."
            )
        cik = str(entry["cik"])
        return {
            "cik": cik,
            "cik_padded": cik.zfill(10),
            "name": entry["name"],
        }

    # ── company filings ───────────────────────────────────────────

    def get_submissions(self, ticker: str) -> Dict[str, Any]:
        """Fetch the full submissions (filing history) for a ticker."""
        info = self.resolve_ticker(ticker)
        cache_key = f"submissions_{info['cik']}"
        cached = self.cache.get("submissions", cache_key)
        if cached is not None:
            return cached

        url = f"{BASE_URL}/submissions/CIK{info['cik_padded']}.json"
        data = self._get(url)
        self.cache.set("submissions", cache_key, data)
        return data

    def get_recent_filings(
        self,
        ticker: str,
        form_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, str]]:
        """
        Return a list of recent filings as dicts with keys:
        accessionNumber, filingDate, form, primaryDocument, etc.
        """
        if form_types is None:
            form_types = ["10-K", "10-Q", "8-K"]

        submissions = self.get_submissions(ticker)
        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            return []

        filings = []
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        for i, form in enumerate(forms):
            if form in form_types and len(filings) < limit:
                filings.append(
                    {
                        "form": form,
                        "filingDate": dates[i],
                        "accessionNumber": accessions[i],
                        "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
                    }
                )
        return filings

    # ── XBRL company facts ────────────────────────────────────────

    def get_company_facts(self, ticker: str) -> Dict[str, Any]:
        """Fetch all XBRL company facts (structured financial data)."""
        info = self.resolve_ticker(ticker)
        cache_key = f"facts_{info['cik']}"
        cached = self.cache.get("xbrl", cache_key)
        if cached is not None:
            return cached

        url = f"{BASE_URL}/api/xbrl/companyfacts/CIK{info['cik_padded']}.json"
        data = self._get(url)
        self.cache.set("xbrl", cache_key, data)
        return data

    # ── filing document text ──────────────────────────────────────

    def get_filing_text(
        self, ticker: str, accession_number: str, document: str
    ) -> str:
        """
        Download the text of a specific filing document.
        Useful for pulling 10-K/10-Q narrative sections.
        """
        info = self.resolve_ticker(ticker)
        accession_clean = accession_number.replace("-", "")
        cache_key = f"doc_{info['cik']}_{accession_clean}_{document}"
        cached = self.cache.get("documents", cache_key)
        if cached is not None:
            return cached

        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{info['cik']}/{accession_clean}/{document}"
        )
        text = self._get_text(url)

        # Cache filing text for 7 days (filings don't change)
        self.cache.set("documents", cache_key, text, ttl=86400 * 7)
        return text

    # ── edgartools integration ──────────────────────────────────────

    def get_edgartools_company(self, ticker: str):
        """
        Return an edgartools Company object for the ticker, cached.
        Returns None if edgartools is disabled or fails.
        """
        if not env_flag("ENABLE_EDGARTOOLS", True):
            return None

        cache_key = f"edgar_company_{ticker.upper()}"
        cached = self.cache.get("edgartools", cache_key)
        if cached is not None:
            return cached

        try:
            from edgar import Company
            company = Company(ticker.upper())
            if company.not_found:
                return None
            # Don't cache the Company object itself (not serializable),
            # just confirm it's valid. Each call is cheap after identity set.
            return company
        except Exception:
            return None

    def get_edgartools_tenk(self, ticker: str):
        """
        Return the latest 10-K TenK object via edgartools.
        Returns None on failure.
        """
        try:
            company = self.get_edgartools_company(ticker)
            if company is None:
                return None
            tenk = company.latest_tenk
            return tenk
        except Exception:
            return None

    def get_edgartools_financials(self, ticker: str):
        """
        Return edgartools Financials object for gap-filling.
        Returns None on failure.
        """
        try:
            company = self.get_edgartools_company(ticker)
            if company is None:
                return None
            return company.get_financials()
        except Exception:
            return None

    # ── convenience: gather all data for a ticker ─────────────────

    def fetch_all_data(self, ticker: str) -> Dict[str, Any]:
        """
        Fetch all relevant SEC data for a ticker in one call.
        Returns a dict with company info, recent filings, and XBRL facts.
        """
        info = self.resolve_ticker(ticker)
        filings = self.get_recent_filings(ticker, form_types=["10-K", "10-Q", "8-K"])
        company_facts = self.get_company_facts(ticker)

        return {
            "ticker": ticker.upper(),
            "company_name": info["name"],
            "cik": info["cik"],
            "recent_filings": filings,
            "company_facts": company_facts,
        }

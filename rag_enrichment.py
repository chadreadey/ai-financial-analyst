"""
RAG (Retrieval Augmented Generation) enrichment via Pinecone.

Queries a Pinecone index populated by warehouse/embedder.py with SEC filing
sections (10-K MD&A, Risk Factors, Business Description).  Each vector ID is
deterministic: {TICKER}_{accession_no_hyphens}_{section_key}.

When ENABLE_RAG is false (default) or Pinecone is unreachable, all functions
return empty results gracefully.
"""

import logging
from typing import Dict, List

from config import settings
from context_budget import trim_text

logger = logging.getLogger(__name__)

_pinecone_index = None
_pinecone_lock = None


def _get_lock():
    global _pinecone_lock
    if _pinecone_lock is None:
        import threading

        _pinecone_lock = threading.Lock()
    return _pinecone_lock


def _get_pinecone_index():
    """Return a cached Pinecone Index instance or None if unavailable."""
    global _pinecone_index
    if _pinecone_index is not None:
        return _pinecone_index

    with _get_lock():
        if _pinecone_index is not None:
            return _pinecone_index
        try:
            from pinecone import Pinecone

            api_key = settings.pinecone_api_key.strip()
            if not api_key:
                return None

            pc = Pinecone(api_key=api_key)
            _pinecone_index = pc.Index(settings.pinecone_index_name)
            return _pinecone_index
        except Exception:
            logger.debug("Pinecone init failed", exc_info=True)
            return None


def query_rag(
    ticker: str,
    query: str = "",
    top_k: int = 0,
) -> List[Dict]:
    """
    Query Pinecone for relevant SEC filing chunks for a given ticker.

    Returns a list of dicts with keys: text, score, source, date, section_key.
    Returns empty list if RAG is disabled or Pinecone is unreachable.
    """
    if not settings.enable_rag:
        return []

    if top_k <= 0:
        top_k = settings.rag_top_k

    index = _get_pinecone_index()
    if index is None:
        return []

    try:
        q = query or (f"{ticker} financial analysis revenue earnings outlook risks business")
        namespace = settings.pinecone_namespace or "__default__"
        results = index.search(
            namespace=namespace,
            query={
                "inputs": {"text": q},
                "top_k": top_k,
                "filter": {"ticker": {"$eq": ticker.upper()}},
            },
            fields=["text", "ticker", "accession", "section_key", "form_type", "filing_date"],
        )

        chunks = []
        for hit in results.result.hits:
            fields = hit.fields or {}
            chunks.append(
                {
                    "text": fields.get("text", ""),
                    "score": float(hit._score),
                    "source": f"{fields.get('form_type', '10-K')} {fields.get('section_key', '')}",
                    "date": fields.get("filing_date", ""),
                    "section_key": fields.get("section_key", ""),
                }
            )
        return chunks

    except Exception:
        logger.debug("RAG query failed for %s", ticker, exc_info=True)
        return []


def format_rag_section(chunks: List[Dict]) -> str:
    """Format RAG chunks into an enrichment text block."""
    if not chunks:
        return ""

    max_chars = settings.rag_max_chars
    lines = ["=== SEC Filing Intelligence (RAG) ==="]

    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "").strip()
        if not text:
            continue
        source = chunk.get("source", "SEC Filing")
        date = chunk.get("date", "")
        score = chunk.get("score", 0)
        header = f"{i}. [{source}]"
        if date:
            header += f" ({date})"
        header += f" relevance: {score:.2f}"
        lines.append(header)
        lines.append(f"   {text[:400]}")

    section = "\n".join(lines)
    return trim_text(section, max_chars)


def fetch_rag_section(ticker: str) -> str:
    """
    Convenience wrapper: query RAG and format the result.
    Returns empty string if RAG is disabled or no results found.
    """
    if not settings.enable_rag:
        return ""

    chunks = query_rag(ticker)
    return format_rag_section(chunks)


# ── time-series RAG ────────────────────────────────────────────────────────


def query_financial_history(
    ticker: str,
    query: str = "",
    top_k: int = 0,
) -> List[Dict]:
    """
    Query the `financial_ts` namespace for historical quarterly financial snapshots
    for a specific ticker.

    Always filters by ticker — never returns another company's records.
    Returns empty list if ENABLE_FINANCIAL_HISTORY_RAG is false or Pinecone is unreachable.
    """
    if not settings.enable_financial_history_rag:
        return []

    if top_k <= 0:
        top_k = settings.rag_financial_history_top_k

    index = _get_pinecone_index()
    if index is None:
        return []

    try:
        q = query or (f"{ticker} quarterly revenue earnings margins cash flow growth")
        namespace = settings.pinecone_financial_ts_namespace
        results = index.search(
            namespace=namespace,
            query={
                "inputs": {"text": q},
                "top_k": top_k,
                "filter": {"ticker": {"$eq": ticker.upper()}},
            },
            fields=[
                "text",
                "ticker",
                "period",
                "quarter_label",
                "revenue",
                "net_income",
                "operating_margin",
                "free_cash_flow",
            ],
        )

        chunks = []
        for hit in results.result.hits:
            fields = hit.fields or {}
            chunks.append(
                {
                    "text": fields.get("text", ""),
                    "score": float(hit._score),
                    "source": f"Financial History {fields.get('quarter_label', '')}",
                    "date": fields.get("period", ""),
                    "quarter_label": fields.get("quarter_label", ""),
                }
            )
        return chunks

    except Exception:
        logger.debug("Financial history RAG query failed for %s", ticker, exc_info=True)
        return []


def query_macro_history(
    query: str = "",
    top_k: int = 0,
) -> List[Dict]:
    """
    Query the `macro_ts` namespace for quarterly macro snapshots.

    No ticker filter — macro snapshots are global.
    Returns empty list if ENABLE_MACRO_HISTORY_RAG is false or Pinecone is unreachable.
    """
    if not settings.enable_macro_history_rag:
        return []

    if top_k <= 0:
        top_k = settings.rag_macro_history_top_k

    index = _get_pinecone_index()
    if index is None:
        return []

    try:
        q = query or (
            "interest rates inflation GDP growth unemployment credit spreads macro regime"
        )
        namespace = settings.pinecone_macro_ts_namespace
        results = index.search(
            namespace=namespace,
            query={
                "inputs": {"text": q},
                "top_k": top_k,
            },
            fields=[
                "text",
                "period",
                "quarter_label",
                "fed_funds",
                "cpi_yoy",
                "real_gdp_growth",
                "hy_spread",
            ],
        )

        chunks = []
        for hit in results.result.hits:
            fields = hit.fields or {}
            chunks.append(
                {
                    "text": fields.get("text", ""),
                    "score": float(hit._score),
                    "source": f"Macro Snapshot {fields.get('quarter_label', '')}",
                    "date": fields.get("period", ""),
                    "quarter_label": fields.get("quarter_label", ""),
                }
            )
        return chunks

    except Exception:
        logger.debug("Macro history RAG query failed", exc_info=True)
        return []


def format_timeseries_rag_section(
    financial_chunks: List[Dict],
    macro_chunks: List[Dict],
) -> str:
    """
    Format financial history and macro history chunks into a combined enrichment block.
    Returns empty string if both lists are empty.
    """
    if not financial_chunks and not macro_chunks:
        return ""

    parts = []

    if financial_chunks:
        lines = ["=== Historical Financial Data (RAG) ==="]
        char_budget = settings.rag_financial_history_max_chars
        used = 0
        for chunk in financial_chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            label = chunk.get("quarter_label", chunk.get("source", ""))
            entry = f"[{label}]\n{text}"
            if used + len(entry) > char_budget:
                break
            lines.append(entry)
            used += len(entry)
        parts.append("\n".join(lines))

    if macro_chunks:
        lines = ["=== Historical Macro Environment (RAG) ==="]
        char_budget = settings.rag_macro_history_max_chars
        used = 0
        for chunk in macro_chunks:
            text = chunk.get("text", "").strip()
            if not text:
                continue
            label = chunk.get("quarter_label", chunk.get("source", ""))
            entry = f"[{label}]\n{text}"
            if used + len(entry) > char_budget:
                break
            lines.append(entry)
            used += len(entry)
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def fetch_timeseries_rag_section(ticker: str) -> str:
    """
    Convenience wrapper: query both financial and macro history RAG and
    return a combined formatted string.
    Returns empty string if both features are disabled or no results found.
    """
    if not settings.enable_financial_history_rag and not settings.enable_macro_history_rag:
        return ""

    financial_chunks = query_financial_history(ticker)
    macro_chunks = query_macro_history()
    return format_timeseries_rag_section(financial_chunks, macro_chunks)


# ── research RAG (Perplexity research library) ──────────────────────────────


def query_research_rag(
    query: str,
    top_k: int = 0,
    category_filter: str = "",
    ticker_filter: str = "",
) -> List[Dict]:
    """
    Query the research namespace for sector landscapes, macro signals,
    signal validation research, and portfolio construction guides.

    Optionally filter by document_category and/or ticker tag.
    When ticker_filter is set, returns only chunks that mention that ticker.
    """
    if not settings.enable_rag:
        return []

    if top_k <= 0:
        top_k = settings.rag_research_top_k

    index = _get_pinecone_index()
    if index is None:
        return []

    try:
        filters = {}
        if category_filter:
            filters["document_category"] = {"$eq": category_filter}
        if ticker_filter:
            filters["tickers"] = {"$in": [ticker_filter.upper()]}

        search_params: dict = {
            "inputs": {"text": query},
            "top_k": top_k,
        }
        if filters:
            search_params["filter"] = filters

        namespace = settings.pinecone_research_namespace
        results = index.search(
            namespace=namespace,
            query=search_params,
            fields=[
                "text",
                "source_file",
                "section_header",
                "document_category",
                "token_count",
                "tickers",
                "data_as_of",
            ],
        )

        chunks = []
        for hit in results.result.hits:
            fields = hit.fields or {}
            chunks.append(
                {
                    "text": fields.get("text", ""),
                    "score": float(hit._score),
                    "source": fields.get("source_file", ""),
                    "section": fields.get("section_header", ""),
                    "category": fields.get("document_category", ""),
                }
            )
        return chunks

    except Exception:
        logger.debug("Research RAG query failed", exc_info=True)
        return []


def format_research_rag_section(chunks: List[Dict]) -> str:
    """Format research RAG chunks into an enrichment text block."""
    if not chunks:
        return ""

    max_chars = settings.rag_research_max_chars
    lines = ["=== Research Intelligence (RAG) ==="]
    used = 0

    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "").strip()
        if not text:
            continue
        source = chunk.get("source", "research")
        section = chunk.get("section", "")
        score = chunk.get("score", 0)
        header = f"{i}. [{source}]"
        if section:
            header += f" > {section}"
        header += f" (relevance: {score:.2f})"
        entry = f"{header}\n   {text[:500]}"
        if used + len(entry) > max_chars:
            break
        lines.append(entry)
        used += len(entry)

    return "\n".join(lines)


def fetch_research_rag_section(ticker: str, sector: str = "") -> str:
    """
    Query research RAG with a ticker+sector context query.
    Uses two parallel strategies and merges results:
      1. Ticker-filtered: chunks that specifically mention this stock
      2. Semantic (unfiltered): sector/macro context, competitor landscapes,
         valuation frameworks — catches competitive analysis that doesn't
         name this specific ticker but covers the sector dynamics
    Deduplicates and returns the combined top-k.
    """
    if not settings.enable_rag:
        return ""

    top_k = settings.rag_research_top_k

    # Strategy 1: ticker-specific chunks
    ticker_query = f"{ticker} {sector} competitive positioning earnings valuation risks"
    ticker_chunks = query_research_rag(ticker_query, ticker_filter=ticker, top_k=top_k)

    # Strategy 2: broad semantic search (catches competitor/sector context)
    sector_query = f"{ticker} {sector} competitive landscape macro risks tariffs industry valuation methodology"
    semantic_chunks = query_research_rag(sector_query, top_k=top_k)

    # Merge: ticker-specific first, then fill with semantic, deduplicated
    seen = set()
    merged = []
    for chunk in ticker_chunks + semantic_chunks:
        key = (chunk["source"], chunk["section"])
        if key not in seen:
            seen.add(key)
            merged.append(chunk)
        if len(merged) >= top_k:
            break

    return format_research_rag_section(merged)

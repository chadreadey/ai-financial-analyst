"""
RAG (Retrieval Augmented Generation) enrichment stub.

This module provides the code interface for querying a Qdrant vector DB
populated with financial research content (analyst newsletters, SEC full-text
search, news articles). The actual data pipeline (n8n + embedding + ingestion)
is a separate infrastructure concern.

When ENABLE_RAG is false (default) or Qdrant is unreachable, all functions
return empty results gracefully.
"""

import logging
from typing import Dict, List

from config import settings
from context_budget import trim_text

logger = logging.getLogger(__name__)


def _get_qdrant_client():
    """Return a Qdrant client instance or None if unavailable."""
    try:
        from qdrant_client import QdrantClient

        return QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            timeout=5,
        )
    except (ImportError, ConnectionError, OSError):
        return None


def query_rag(
    ticker: str,
    query: str = "",
    top_k: int = 0,
) -> List[Dict]:
    """
    Query the vector DB for relevant research chunks.

    Returns a list of dicts with keys: text, score, source, date.
    Returns empty list if RAG is disabled or Qdrant is unreachable.
    """
    if not settings.enable_rag:
        return []

    if top_k <= 0:
        top_k = settings.rag_top_k

    collection = settings.qdrant_collection
    embed_key = (settings.openai_embed_key or settings.openai_api_key).strip()

    if not embed_key:
        return []

    client = _get_qdrant_client()
    if client is None:
        return []

    try:
        import openai
        embed_client = openai.OpenAI(api_key=embed_key)
        response = embed_client.embeddings.create(
            model="text-embedding-3-small",
            input=query or f"{ticker} financial analysis outlook",
        )
        query_vector = response.data[0].embedding

        results = client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            query_filter={
                "must": [
                    {"key": "ticker", "match": {"value": ticker.upper()}}
                ]
            },
        )

        chunks = []
        for hit in results:
            payload = hit.payload or {}
            chunks.append({
                "text": payload.get("text", ""),
                "score": float(hit.score),
                "source": payload.get("source", "unknown"),
                "date": payload.get("date", ""),
            })
        return chunks

    except Exception:
        logger.debug("RAG query failed for %s", ticker, exc_info=True)
        return []


def format_rag_section(chunks: List[Dict]) -> str:
    """Format RAG chunks into an enrichment text block."""
    if not chunks:
        return ""

    max_chars = settings.rag_max_chars
    lines = ["=== Research Intelligence (RAG) ==="]

    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "").strip()
        if not text:
            continue
        source = chunk.get("source", "unknown")
        date = chunk.get("date", "")
        score = chunk.get("score", 0)
        header = f"{i}. [{source}]"
        if date:
            header += f" ({date})"
        header += f" relevance: {score:.2f}"
        lines.append(header)
        lines.append(f"   {text}")

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

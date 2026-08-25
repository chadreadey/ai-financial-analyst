import logging
import time

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

_news_cache: dict[str, tuple[float, list[dict]]] = {}
CACHE_TTL = 300


@router.get("/")
async def get_news(ticker: str = "", sector: str = "", limit: int = 10):
    from config import settings

    key = f"{ticker}:{sector}"
    now = time.time()

    cached = _news_cache.get(key)
    if cached and (now - cached[0]) < CACHE_TTL:
        return {"items": cached[1][:limit]}

    if not settings.tavily_api_key.strip():
        return {"items": []}

    try:
        from importlib import import_module

        tavily_mod = import_module("tavily")
        client = tavily_mod.TavilyClient(api_key=settings.tavily_api_key.strip())

        query_parts = []
        if ticker:
            query_parts.append(f"{ticker} stock")
        if sector:
            query_parts.append(f"{sector} sector")
        query_parts.append("financial news latest developments")
        query = " ".join(query_parts)

        results = client.search(
            query=query,
            topic="news",
            days=7,
            search_depth="basic",
            max_results=limit,
        )

        items = []
        for r in results.get("results", [])[:limit]:
            items.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": (r.get("content", "") or "")[:300],
                    "source": r.get("url", "").split("/")[2] if r.get("url") else "",
                    "date": "",
                    "sector": sector,
                }
            )

        _news_cache[key] = (now, items)
        return {"items": items}

    except Exception as exc:
        logger.warning("News fetch failed: %s", exc)
        return {"items": []}


@router.get("/macro")
async def get_macro_news():
    return await get_news(ticker="", sector="", limit=5)

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(Path(project_root) / ".env")

from config import settings

logging.basicConfig(
    format="%(levelname)s | %(name)s | %(message)s",
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
)

_dsn = os.getenv("SENTRY_DSN", "")
if _dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(
            dsn=_dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            integrations=[FastApiIntegration()],
            traces_sample_rate=0.1,
        )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="AI Financial Analyst API",
    version="0.1.0",
    lifespan=lifespan,
)

_default_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]
_extra = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = _default_origins + _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import analysis, reports, config as config_router
from backend.routers import portfolio, news, industry
from backend.routers import watchlist, market_data, recommendations
from backend.routers import backtest, paper_trading

app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(config_router.router, prefix="/api/config", tags=["config"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(news.router, prefix="/api/news", tags=["news"])
app.include_router(industry.router, prefix="/api/industry", tags=["industry"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["watchlist"])
app.include_router(market_data.router, prefix="/api/market", tags=["market"])
app.include_router(recommendations.router, prefix="/api/recommendations", tags=["recommendations"])
app.include_router(backtest.router, prefix="/api/backtest", tags=["backtest"])
app.include_router(paper_trading.router, prefix="/api/paper-trading", tags=["paper-trading"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}

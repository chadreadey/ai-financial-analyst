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

logger = logging.getLogger(__name__)

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
    # Start paper trading scheduler if Alpaca keys are configured
    _scheduler = None
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        try:
            from backend.paper_scheduler import create_scheduler

            _scheduler = create_scheduler(start=True)
            logger.info("Paper trading scheduler started")
        except Exception as exc:
            logger.warning("Failed to start paper trading scheduler: %s", exc)
    try:
        yield
    finally:
        # Drain in-flight Modal CPCV dispatch threads so runs are finalized
        # (status, Supabase flush) before the process exits. Bounded join
        # — we do not block SIGTERM forever.
        try:
            from modal_app.dispatcher import snapshot_active_threads

            threads = snapshot_active_threads()
            if threads:
                logger.info(
                    "lifespan: joining %d in-flight CPCV dispatch thread(s)",
                    len(threads),
                )
            deadline_seconds = 30.0
            per_thread_budget = max(0.1, deadline_seconds / max(1, len(threads)))
            for t in threads:
                t.join(timeout=per_thread_budget)
                if t.is_alive():
                    logger.warning(
                        "lifespan: CPCV dispatch thread %s still running after "
                        "%.1fs — proceeding with shutdown; stale sweeper will finalize",
                        t.name,
                        per_thread_budget,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("lifespan CPCV thread drain failed: %s", exc)
        if _scheduler:
            _scheduler.shutdown(wait=False)


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
    # TODO: replace `ai-financial-analyst` with actual Vercel project slug if different.
    # Lookup: Vercel dashboard > project > Settings > Domains.
    allow_origin_regex=r"https://ai-financial-analyst(-[a-z0-9]+)?\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.routers import analysis, reports, config as config_router
from backend.routers import portfolio, news, industry
from backend.routers import watchlist, market_data, recommendations
from backend.routers import backtest, paper_trading, backtest_modal
from backend.routers import diagnostics

# Point the stochastic assumption logger at the configured JSONL sink so any
# instrumented statistical routine streams its assumption checks to disk.
try:
    from quant.assumption_audit import configure_default_log
    configure_default_log(
        enabled=settings.assumption_audit_enabled,
        jsonl_path=settings.assumption_audit_log_path,
    )
except Exception as exc:  # pragma: no cover - never block startup on this
    logger.warning("assumption audit log not configured: %s", exc)

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
app.include_router(backtest_modal.router, prefix="/api/backtest", tags=["backtest-modal"])
app.include_router(paper_trading.router, prefix="/api/paper-trading", tags=["paper-trading"])
app.include_router(diagnostics.router, prefix="/api/diagnostics", tags=["diagnostics"])


@app.get("/api/health")
async def health():
    return {"status": "ok"}

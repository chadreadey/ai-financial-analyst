from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class RunAnalysisRequest(BaseModel):
    ticker: str
    provider: str = "openai"
    model: Optional[str] = None
    api_key: Optional[str] = None
    enable_tiingo: bool = True
    enable_fmp: bool = True
    enable_yahoo: bool = True
    enable_tavily: bool = True
    max_agent_context_chars: int = 12000
    max_agent_output_tokens: int = 1200
    synthesis_report_max_chars: int = 4500
    synthesis_input_max_chars: int = 22000
    max_synthesis_output_tokens: int = 1500


class JobCreated(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # pending | running | complete | error
    error: Optional[str] = None


class ProgressEvent(BaseModel):
    step: str
    pct: Optional[int] = None


class HistoryEntry(BaseModel):
    analysis_id: str = ""
    run_at: float
    ticker: str
    company_name: str = ""
    verdict: str = ""
    conviction: str = ""
    time_horizon: str = ""
    composite_score: Optional[float] = None
    price_target: Optional[float] = None
    stop_loss_value: Optional[float] = None
    stop_loss_unit: str = ""
    entry_price_at_run: Optional[float] = None
    current_price: Optional[float] = None
    return_since_analysis_pct: Optional[float] = None
    outcome_status: str = "unknown"
    days_remaining: Optional[int] = None


class HistoryDetail(HistoryEntry):
    health_scores: dict[str, Any] = Field(default_factory=dict)
    result_json: Optional[dict[str, Any]] = None


class ConfigDefaults(BaseModel):
    providers: list[str] = ["openai", "anthropic"]
    enable_tiingo: bool = True
    enable_fmp: bool = True
    enable_yahoo: bool = True
    enable_tavily: bool = True
    max_agent_context_chars: int = 12000
    max_agent_output_tokens: int = 1200
    synthesis_report_max_chars: int = 4500
    synthesis_input_max_chars: int = 22000
    max_synthesis_output_tokens: int = 1500


class PortfolioHolding(BaseModel):
    ticker: str
    shares: float
    cost_basis: float
    date_added: str = ""


class PortfolioSummary(BaseModel):
    holdings: list[PortfolioHolding] = Field(default_factory=list)
    total_value: float = 0.0
    total_cost: float = 0.0
    day_change_pct: float = 0.0
    allocations: dict[str, float] = Field(default_factory=dict)


class NewsItem(BaseModel):
    title: str
    url: str
    snippet: str
    source: str = ""
    date: str = ""
    sector: str = ""


class SectorOverview(BaseModel):
    sector: str
    etf_symbol: str = ""
    ytd_return_pct: Optional[float] = None
    ticker_count: int = 0


class WatchlistEntry(BaseModel):
    ticker: str
    added_at: str = ""
    latest_verdict: Optional[str] = None
    latest_conviction: Optional[str] = None
    latest_score: Optional[float] = None


class WatchlistSummary(BaseModel):
    ticker: str
    current_price: Optional[float] = None
    hit_rate_pct: Optional[float] = None
    alpha_vs_spy: Optional[float] = None
    period_statuses: dict[str, str] = Field(default_factory=dict)


class PriceBar(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class RecommendationRecord(BaseModel):
    run_at: float
    verdict: str = ""
    conviction: str = ""
    composite_score: Optional[float] = None
    entry_price: Optional[float] = None
    target_price: Optional[float] = None
    time_horizon: Optional[str] = None
    outcome: Optional[str] = None
    outcome_price: Optional[float] = None
    outcome_date: Optional[str] = None


class BacktestConfig(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""


class NLBacktestRequest(BaseModel):
    query: str


class BacktestRunCreated(BaseModel):
    job_id: str
    config_version: str = "1"
    parsed_config: BacktestConfig
    parse_notes: str = ""


class BacktestResult(BaseModel):
    status: str = "pending"
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    hit_rate_pct: Optional[float] = None
    equity_curve: list[dict] = Field(default_factory=list)
    trade_log: list[dict] = Field(default_factory=list)
    walk_forward: list[dict] = Field(default_factory=list)


class PaperPosition(BaseModel):
    ticker: str
    entry_price: float
    entry_date: str = ""
    current_price: Optional[float] = None
    verdict: str = ""
    exit_conditions: str = ""


class PaperMetrics(BaseModel):
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    win_rate_pct: Optional[float] = None
    total_pnl_pct: Optional[float] = None
    total_trades: int = 0

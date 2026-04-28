export interface AgentReport {
  agent_name: string;
  analysis: string;
}

export interface AnalysisResult {
  ticker: string;
  company_name: string;
  agent_reports: AgentReport[];
  synthesis: string;
  structured_verdict: Record<string, any> | null;
  metrics: Record<string, any>;
  enrichment_warnings: string[];
  enrichment_sources: string[];
  enrichment_filter_stats: Record<string, number>;
}

export interface ProgressEvent {
  step: string;
  pct?: number;
  result?: AnalysisResult;
  error?: string;
}

export interface JobCreated {
  job_id: string;
}

export interface HistoryEntry {
  analysis_id: string;
  run_at: number;
  ticker: string;
  company_name: string;
  verdict: string;
  conviction: string;
  time_horizon: string;
  composite_score: number | null;
  price_target: number | null;
  stop_loss_value: number | null;
  stop_loss_unit: string;
  entry_price_at_run: number | null;
  current_price: number | null;
  return_since_analysis_pct: number | null;
  outcome_status: string;
  days_remaining: number | null;
}

export interface HistoryDetail extends HistoryEntry {
  health_scores: Record<string, any>;
  result_json: Record<string, any> | null;
}

export interface ConfigDefaults {
  providers: string[];
  enable_tiingo: boolean;
  enable_fmp: boolean;
  enable_yahoo: boolean;
  enable_tavily: boolean;
  max_agent_context_chars: number;
  max_agent_output_tokens: number;
  synthesis_report_max_chars: number;
  synthesis_input_max_chars: number;
  max_synthesis_output_tokens: number;
}

export interface RunAnalysisRequest {
  ticker: string;
  provider: string;
  model?: string;
  api_key?: string;
  enable_tiingo: boolean;
  enable_fmp: boolean;
  enable_yahoo: boolean;
  enable_tavily: boolean;
  max_agent_context_chars: number;
  max_agent_output_tokens: number;
  synthesis_report_max_chars: number;
  synthesis_input_max_chars: number;
  max_synthesis_output_tokens: number;
}

export interface ReportFile {
  filename: string;
  size: number;
  modified: number;
  has_pdf: boolean;
}

export interface PortfolioHolding {
  ticker: string;
  shares: number;
  cost_basis: number;
  date_added: string;
}

export interface PortfolioSummary {
  holdings: PortfolioHolding[];
  total_value: number;
  total_cost: number;
  day_change_pct: number;
  allocations: Record<string, number>;
}

export interface NewsItem {
  title: string;
  url: string;
  snippet: string;
  source: string;
  date: string;
  sector: string;
}

export interface SectorOverview {
  sector: string;
  etf_symbol: string;
  ytd_return_pct: number | null;
  ticker_count: number;
}

export interface WatchlistEntry {
  ticker: string;
  added_at: string;
  latest_verdict?: string | null;
  latest_conviction?: string | null;
  latest_score?: number | null;
}

export interface WatchlistSummary {
  ticker: string;
  current_price?: number | null;
  hit_rate_pct?: number | null;
  alpha_vs_spy?: number | null;
  period_statuses: Record<string, string>;
}

export interface PriceBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface RecommendationRecord {
  run_at: number;
  verdict: string;
  conviction: string;
  composite_score: number | null;
  entry_price: number | null;
  target_price: number | null;
  time_horizon: string | null;
  outcome: string | null;
  outcome_price: number | null;
  outcome_date: string | null;
}

export interface SparklineData {
  ticker: string;
  closes: number[];
  dates: string[];
}

export interface BacktestConfig {
  tickers: string[];
  start_date: string;
  end_date: string;
}

export interface BacktestResult {
  status: string;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown_pct: number | null;
  win_rate_pct: number | null;
  hit_rate_pct: number | null;
  equity_curve: { date: string; equity: number }[];
  trade_log: Record<string, any>[];
  walk_forward: Record<string, any>[];
}

export interface PaperPosition {
  ticker: string;
  entry_price: number;
  entry_date: string;
  current_price: number | null;
  verdict: string;
  exit_conditions: string;
}

export interface PaperMetrics {
  sharpe: number | null;
  sortino: number | null;
  win_rate_pct: number | null;
  total_pnl_pct: number | null;
  total_trades: number;
}

export interface AlpacaAccount {
  cash: number;
  equity: number;
  buying_power: number;
  portfolio_value: number;
  currency: string;
  error?: string;
}

export interface AlpacaOrder {
  order_id: string;
  symbol: string;
  qty: number;
  side: string;
  status: string;
  filled_avg_price: number | null;
  filled_at: string | null;
  submitted_at: string | null;
  order_type: string;
}

export interface RebalanceResult {
  status: string;
  closed: string[];
  opened: string[];
  errors: string[];
}

// ── Modal CPCV backtest types ────────────────────────────────────────────

export type ModalRunStatus = "queued" | "running" | "complete" | "degraded" | "failed";

export interface ModalRun {
  run_id: string;
  config_hash: string;
  git_sha: string;
  status: ModalRunStatus;
  universe: string | null;
  n_groups: number | null;
  n_test_groups: number | null;
  n_combinations: number | null;
  n_completed: number;
  n_skipped: number;
  n_failed: number;
  median_oos_sharpe: number | null;
  oos_sharpe_min: number | null;
  oos_sharpe_max: number | null;
  pbo: number | null;
  deflated_sharpe: number | null;
  config_json: Record<string, any>;
  metrics_json: Record<string, any> | null;
  error: string | null;
  modal_call_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

export interface ModalCombination {
  run_id: string;
  combo_idx: number;
  status: "complete" | "skipped" | "error";
  train_indices: number[] | null;
  test_indices: number[] | null;
  oos_sharpe: number | null;
  return_pct: number | null;
  n_trades: number | null;
  n_test_dates: number | null;
  elapsed_seconds: number | null;
  git_sha: string | null;
  error: string | null;
  gates_json: Record<string, any> | null;
  created_at: string | null;
}

export interface ModalTrade {
  run_id: string;
  combo_idx: number;
  trade_idx: number;
  ticker: string;
  direction: "LONG" | "SHORT";
  entry_date: string;
  exit_date: string | null;
  entry_price: number | null;
  exit_price: number | null;
  pnl_dollar: number | null;
  pnl_pct: number | null;
  holding_days: number | null;
  exit_reason: string | null;
  composite_score: number | null;
  regime_at_entry: string | null;
  /**
   * Full SignalVector snapshot taken at entry. Shape is the TradeRecord
   * payload serialised by `quant/backtest.py::TradeRecord.to_json_dict`:
   * `{ flags: string[], actionable: bool, signal_vector: { [signal]: { score: number, detail?: string, ... } } }`.
   * Some older rows persisted only the flat score map — callers should
   * tolerate both shapes via the helper in `modal-format.tsx`.
   */
  signals_at_entry_json: Record<string, any> | null;
  flags_json: string[] | Record<string, any> | null;
  created_at: string | null;
}

export type ModalEventKind =
  | "run_started"
  | "run_completed"
  | "run_failed"
  | "run_degraded"
  | "combo_started"
  | "combo_completed"
  | "combo_failed"
  | "combo_skipped";

export interface ModalEvent {
  id: number;
  run_id: string;
  kind: ModalEventKind;
  combo_idx: number | null;
  payload: Record<string, any> | null;
  created_at: string | null;
}

export interface ModalRunKickoff {
  run_id: string;
  config_hash: string;
  git_sha: string;
  status: "queued";
}

export interface ModalRunRequest {
  tickers?: string[];
  universe?: "liquid_10" | "liquid_20" | "liquid_50" | string;
  start_date?: string;
  end_date?: string;
  n_groups?: number;
  n_test_groups?: number;
  purge_months?: number;
  embargo_months?: number;
  max_combos?: number;
  seed?: number;
  local?: boolean;
}

// ── Portfolio dashboard types (dashboard-v1) ────────────────────────────

export interface LatestVerdict {
  analysis_id: string;
  verdict: string;
  conviction: string;
  composite_score: number | null;
  price_target: number | null;
  implied_upside_pct: number | null;
  as_of: string;
  run_at: number;
  days_stale: number | null;
}

export interface PositionWithVerdict {
  ticker: string;
  entry_price: number;
  entry_date: string;
  current_price: number | null;
  entry_verdict: string;
  exit_conditions: string;
  direction: string;
  conviction_score: number | null;
  unrealized_pnl_pct: number | null;
  days_held: number;
  latest_verdict: LatestVerdict | null;
}

export interface PortfolioOverviewTotals {
  total_positions: number;
  total_equity_at_entry: number;
  avg_unrealized_pnl_pct: number | null;
  stale_count: number;
}

export interface PortfolioOverviewResponse {
  positions: PositionWithVerdict[];
  totals: PortfolioOverviewTotals;
}

export interface CandidateSignal {
  name: string;
  score: number;
}

export interface PortfolioCandidate {
  ticker: string;
  composite_score: number;
  composite_direction: string;
  actionable: boolean;
  top_signals: CandidateSignal[];
  cached_at: string;
}

export interface PortfolioCandidatesResponse {
  candidates: PortfolioCandidate[];
  cached_at: string;
  universe: string;
  errors: string[];
}

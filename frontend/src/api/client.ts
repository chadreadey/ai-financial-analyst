// In prod, `/api/backtest/modal/*` hits a Vercel serverless function that
// injects the server-side INTERNAL_API_KEY before forwarding to Railway.
// All other `/api/*` paths flow through the rewrite in vercel.json.
// In local dev (vite dev server), set VITE_API_URL to your local backend
// and put INTERNAL_API_KEY in backend .env for the router to accept requests.
const API_URL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  runAnalysis: (body: import("./types").RunAnalysisRequest) =>
    request<import("./types").JobCreated>("/api/analysis/run", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getResult: (jobId: string) =>
    request<any>(`/api/analysis/result/${jobId}`),

  getHistory: (ticker?: string, limit: number = 20, offset: number = 0) =>
    request<{ entries: import("./types").HistoryEntry[] }>(
      `/api/analysis/history?${new URLSearchParams({
        ...(ticker ? { ticker } : {}),
        limit: String(limit),
        offset: String(offset),
      }).toString()}`
    ),

  getHistoryDetail: (analysisId: string) =>
    request<import("./types").HistoryDetail>(`/api/analysis/history/${analysisId}`),

  getDefaults: () =>
    request<import("./types").ConfigDefaults>("/api/config/defaults"),

  listReports: () =>
    request<{ reports: import("./types").ReportFile[] }>("/api/reports/"),

  getReportText: (filename: string) =>
    request<{ filename: string; content: string }>(`/api/reports/${filename}`),

  getPdfUrl: (filename: string) =>
    `${API_URL}/api/reports/${filename}/pdf`,

  getPortfolio: () =>
    request<import("./types").PortfolioSummary>("/api/portfolio/"),

  upsertHolding: (holding: import("./types").PortfolioHolding) =>
    request<{ status: string }>("/api/portfolio/holdings", {
      method: "POST",
      body: JSON.stringify(holding),
    }),

  deleteHolding: (ticker: string) =>
    request<{ status: string }>(`/api/portfolio/holdings/${ticker}`, {
      method: "DELETE",
    }),

  getNews: (params?: { ticker?: string; sector?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.ticker) qs.set("ticker", params.ticker);
    if (params?.sector) qs.set("sector", params.sector);
    if (params?.limit) qs.set("limit", String(params.limit));
    return request<{ items: import("./types").NewsItem[] }>(`/api/news/?${qs}`);
  },

  getSectors: () =>
    request<{ sectors: import("./types").SectorOverview[] }>("/api/industry/sectors"),

  getWatchlist: () =>
    request<{ entries: import("./types").WatchlistEntry[] }>("/api/watchlist/"),

  addToWatchlist: (ticker: string) =>
    request<{ status: string }>(`/api/watchlist/${ticker}`, { method: "POST" }),

  removeFromWatchlist: (ticker: string) =>
    request<{ status: string }>(`/api/watchlist/${ticker}`, { method: "DELETE" }),

  getWatchlistSummary: (ticker: string) =>
    request<import("./types").WatchlistSummary>(`/api/watchlist/${ticker}/summary`),

  getPriceHistory: (ticker: string, period: string = "1yr") =>
    request<{ ticker: string; bars: import("./types").PriceBar[] }>(
      `/api/market/price-history/${ticker}?period=${period}`
    ),

  getSparkline: (ticker: string) =>
    request<import("./types").SparklineData>(`/api/market/sparkline/${ticker}`),

  getRecommendationHistory: (ticker: string) =>
    request<{ records: import("./types").RecommendationRecord[] }>(
      `/api/recommendations/history/${ticker}`
    ),

  streamUrl: (jobId: string) => `${API_URL}/api/analysis/stream/${jobId}`,

  runBacktest: (config: import("./types").BacktestConfig) =>
    request<{ job_id: string }>("/api/backtest/run", {
      method: "POST",
      body: JSON.stringify(config),
    }),

  runBacktestNl: (query: string) =>
    request<{
      job_id: string;
      config_version: string;
      parsed_config: import("./types").BacktestConfig;
      parse_notes: string;
    }>("/api/backtest/nl", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  getBacktestResult: (jobId: string) =>
    request<import("./types").BacktestResult>(`/api/backtest/result/${jobId}`),

  getBacktestHistory: () =>
    request<{ runs: Array<Record<string, any>> }>("/api/backtest/history"),

  getPaperPositions: () =>
    request<{ positions: any[] }>("/api/paper-trading/positions"),

  addPaperPosition: (position: any) =>
    request<{ status: string }>("/api/paper-trading/positions", {
      method: "POST",
      body: JSON.stringify(position),
    }),

  closePaperPosition: (ticker: string, body: { exit_price: number; exit_reason: string }) =>
    request<{ status: string; pnl_pct: number }>(`/api/paper-trading/positions/${ticker}/close`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  getPaperHistory: () =>
    request<{ trades: any[]; equity_curve: { date: string; equity: number }[] }>("/api/paper-trading/history"),

  getPaperMetrics: () =>
    request<import("./types").PaperMetrics>("/api/paper-trading/metrics"),

  getAlpacaAccount: (): Promise<import("./types").AlpacaAccount> =>
    request<import("./types").AlpacaAccount>("/api/paper-trading/account"),

  getAlpacaOrders: (): Promise<{ orders: import("./types").AlpacaOrder[] }> =>
    request<{ orders: import("./types").AlpacaOrder[] }>("/api/paper-trading/orders"),

  triggerRebalance: (tickers?: string[]): Promise<import("./types").RebalanceResult> =>
    request<import("./types").RebalanceResult>("/api/paper-trading/rebalance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(tickers ? { tickers } : {}),
    }),

  // ── Modal CPCV backtests ─────────────────────────────────────────────
  listModalRuns: (params: {
    status?: import("./types").ModalRunStatus;
    config_hash?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.config_hash) qs.set("config_hash", params.config_hash);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    return request<{ source: string; runs: import("./types").ModalRun[]; count: number }>(
      `/api/backtest/modal/runs?${qs}`
    );
  },

  getModalRun: (runId: string) =>
    request<import("./types").ModalRun>(`/api/backtest/modal/runs/${runId}`),

  listModalRunsByConfigHash: (configHash: string, limit: number = 20) =>
    request<{ config_hash: string; runs: import("./types").ModalRun[]; count: number }>(
      `/api/backtest/modal/runs/by-config-hash/${encodeURIComponent(configHash)}?limit=${limit}`
    ),

  getModalRunCombinations: (runId: string, params: {
    order_by?: "oos_sharpe" | "combo_idx" | "return_pct" | "n_trades";
    descending?: boolean;
    limit?: number;
    offset?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.order_by) qs.set("order_by", params.order_by);
    if (params.descending != null) qs.set("descending", String(params.descending));
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    return request<{
      run_id: string;
      combinations: import("./types").ModalCombination[];
      count: number;
    }>(`/api/backtest/modal/runs/${runId}/combinations?${qs}`);
  },

  getModalComboTrades: (runId: string, comboIdx: number, params: {
    ticker?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.ticker) qs.set("ticker", params.ticker);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    return request<{
      run_id: string;
      combo_idx: number;
      trades: import("./types").ModalTrade[];
      count: number;
    }>(`/api/backtest/modal/runs/${runId}/combinations/${comboIdx}/trades?${qs}`);
  },

  getModalRunTrades: (runId: string, params: { ticker?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.ticker) qs.set("ticker", params.ticker);
    if (params.limit != null) qs.set("limit", String(params.limit));
    if (params.offset != null) qs.set("offset", String(params.offset));
    return request<{
      run_id: string;
      trades: import("./types").ModalTrade[];
      count: number;
    }>(`/api/backtest/modal/runs/${runId}/trades?${qs}`);
  },

  getModalRunEvents: (runId: string, params: { after_id?: number; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.after_id != null) qs.set("after_id", String(params.after_id));
    if (params.limit != null) qs.set("limit", String(params.limit));
    return request<{
      run_id: string;
      events: import("./types").ModalEvent[];
      count: number;
    }>(`/api/backtest/modal/runs/${runId}/events?${qs}`);
  },

  dispatchModalRun: (body: import("./types").ModalRunRequest) =>
    request<import("./types").ModalRunKickoff>("/api/backtest/modal", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

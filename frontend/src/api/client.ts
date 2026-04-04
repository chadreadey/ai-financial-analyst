const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
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
};

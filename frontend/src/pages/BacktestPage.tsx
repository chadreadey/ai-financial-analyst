import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { BacktestConfigPanel } from "../components/backtest/BacktestConfigPanel";
import { BacktestMetricsPanel } from "../components/backtest/BacktestMetricsPanel";
import { TradeLogTable } from "../components/backtest/TradeLogTable";
import { EquityCurveChart } from "../components/charts/EquityCurveChart";
import { useBacktest } from "../hooks/useBacktest";

export function BacktestPage() {
  const { isRunning, result, error, run, runNaturalLanguage, parsedConfig, history, refreshHistory } = useBacktest();
  const [nlQuery, setNlQuery] = useState("");

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
        Backtesting
      </h1>

      <Card>
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Natural Language Backtest
        </h3>
        <textarea
          value={nlQuery}
          onChange={(e) => setNlQuery(e.target.value)}
          rows={3}
          placeholder="Example: Backtest AAPL, MSFT, and NVDA from 2022-01-01 to today based on historical analysis recommendations."
          className="w-full rounded px-3 py-2 text-sm mb-3"
          style={{
            background: "var(--bg-primary)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        />
        <button
          onClick={() => runNaturalLanguage(nlQuery)}
          disabled={isRunning || !nlQuery.trim()}
          className="px-4 py-2 rounded text-sm font-medium"
          style={{
            background: isRunning ? "var(--bg-hover)" : "var(--accent-blue)",
            color: isRunning ? "var(--text-muted)" : "white",
          }}
        >
          Run NL Backtest
        </button>
      </Card>

      {parsedConfig && (
        <Card>
          <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
            Parsed Backtest Config
          </h3>
          <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Tickers: {parsedConfig.tickers.join(", ")} | Start: {parsedConfig.start_date} | End: {parsedConfig.end_date}
          </div>
        </Card>
      )}

      <BacktestConfigPanel onSubmit={run} isRunning={isRunning} />

      {isRunning && (
        <Card>
          <div className="flex items-center gap-3 py-4">
            <div className="w-5 h-5 border-2 border-t-transparent rounded-full animate-spin"
              style={{ borderColor: "var(--accent-blue)", borderTopColor: "transparent" }} />
            <span style={{ color: "var(--text-secondary)" }}>Running backtest...</span>
          </div>
        </Card>
      )}

      {error && (
        <Card>
          <p style={{ color: "var(--accent-red)" }}>{error}</p>
        </Card>
      )}

      {result && result.status === "insufficient_data" && (
        <Card>
          <p style={{ color: "var(--accent-amber)" }}>
            Insufficient data — need at least 10 analysis recommendations in history to run a backtest.
          </p>
        </Card>
      )}

      {result && result.status === "complete" && (
        <>
          <BacktestMetricsPanel
            sharpe={result.sharpe}
            sortino={result.sortino}
            calmar={result.calmar}
            maxDrawdown={result.max_drawdown_pct}
            winRate={result.win_rate_pct}
            hitRate={result.hit_rate_pct}
          />

          {result.equity_curve.length > 0 && (
            <Card>
              <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
                Equity Curve
              </h3>
              <EquityCurveChart data={result.equity_curve} />
            </Card>
          )}

          {result.trade_log.length > 0 && (
            <Card>
              <TradeLogTable trades={result.trade_log} />
            </Card>
          )}
        </>
      )}

      <Card>
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
          Saved Backtest Runs
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Run At", "Config", "NL Query", "Version"].map((h) => (
                  <th key={h} className="text-left py-2 px-2 font-medium" style={{ color: "var(--text-muted)" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((row: any) => (
                <tr key={row.id} style={{ borderBottom: "1px solid var(--border-subtle, var(--border))" }}>
                  <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>
                    {row.run_at ? new Date(row.run_at * 1000).toLocaleString() : "—"}
                  </td>
                  <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>
                    {row.config_json || "—"}
                  </td>
                  <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>
                    {row.nl_query || "—"}
                  </td>
                  <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>
                    {row.config_version || "—"}
                  </td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr>
                  <td className="py-2 px-2" colSpan={4} style={{ color: "var(--text-muted)" }}>
                    No saved backtests yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

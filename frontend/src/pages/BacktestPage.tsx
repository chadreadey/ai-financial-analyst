import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { RunSelector } from "../components/backtest/RunSelector";
import { PerformanceTab } from "../components/backtest/PerformanceTab";
import { TradeDetailRow } from "../components/backtest/TradeDetailRow";
import {
  NewBacktestDialog,
  type NewBacktestSubmission,
} from "../components/backtest/NewBacktestDialog";
import { ModalRunsPanel } from "../components/backtest/ModalRunsPanel";
import { useBacktest } from "../hooks/useBacktest";
import { useDispatchModalRun } from "../hooks/useModalBacktests";
import { Download, Plus } from "lucide-react";

function buildRunSelectorItems(
  history: Record<string, any>[],
): Array<{ id: string; config_summary: string; sharpe: number | null; pbo?: number | null; date: string }> {
  return history.map((r) => {
    let configSummary = "—";
    try {
      const cfg = typeof r.config_json === "string" ? JSON.parse(r.config_json) : r.config_json;
      if (cfg?.tickers) {
        configSummary = cfg.tickers.slice(0, 3).join(", ") + (cfg.tickers.length > 3 ? " …" : "");
      }
    } catch {
      configSummary = r.nl_query ? r.nl_query.slice(0, 40) : r.config_json ?? "—";
    }
    const date = r.run_at ? new Date(r.run_at * 1000).toLocaleDateString() : "—";
    return {
      id: String(r.id),
      config_summary: configSummary,
      sharpe: r.sharpe ?? null,
      pbo: r.pbo ?? null,
      date,
    };
  });
}

function exportCsv(trades: Record<string, any>[]) {
  if (trades.length === 0) return;
  const keys = Object.keys(trades[0]);
  const rows = [keys.join(","), ...trades.map((t) => keys.map((k) => String(t[k] ?? "")).join(","))];
  const blob = new Blob([rows.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "backtest_trades.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function BacktestPage() {
  const navigate = useNavigate();
  const { isRunning, result, error, run, history, refreshHistory } = useBacktest();
  const { dispatch: dispatchModal, isDispatching: isModalDispatching } = useDispatchModalRun();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [dispatchError, setDispatchError] = useState<string | null>(null);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const handleSubmit = async (sub: NewBacktestSubmission) => {
    setDialogOpen(false);
    setDispatchError(null);
    if (sub.kind === "legacy") {
      run(sub.config);
    } else {
      try {
        const kickoff = await dispatchModal(sub.config);
        navigate(`/backtest/modal/runs/${kickoff.run_id}`);
      } catch (e: any) {
        setDispatchError(e?.message ?? "Failed to dispatch Modal run");
      }
    }
  };

  const selectorRuns = buildRunSelectorItems(history);

  const equityCurve = result?.equity_curve ?? [];
  const sharpe = result?.sharpe ?? null;
  const maxDrawdown = result?.max_drawdown_pct ?? null;
  const tradeLog: Record<string, any>[] = result?.trade_log ?? [];

  const totalReturn =
    equityCurve.length >= 2
      ? ((equityCurve[equityCurve.length - 1].equity - equityCurve[0].equity) /
          equityCurve[0].equity) *
        100
      : null;
  const alpha: number | null = null;
  const hasResults = result?.status === "complete";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-foreground">Backtest Lab</h1>
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={() => setDialogOpen(true)}
            disabled={isRunning || isModalDispatching}
          >
            <Plus size={13} className="mr-1.5" />
            New Backtest
          </Button>
        </div>
      </div>

      {dispatchError && (
        <Card className="p-3">
          <p className="text-xs text-[--negative]">{dispatchError}</p>
        </Card>
      )}

      <Tabs defaultValue="modal">
        <TabsList className="mb-3">
          <TabsTrigger value="modal">Modal CPCV</TabsTrigger>
          <TabsTrigger value="legacy">Legacy (in-process)</TabsTrigger>
        </TabsList>

        <TabsContent value="modal">
          <ModalRunsPanel />
        </TabsContent>

        <TabsContent value="legacy">
          <div className="space-y-4">
            {selectorRuns.length > 0 && (
              <RunSelector
                runs={selectorRuns}
                selectedId={selectedRunId}
                onSelect={setSelectedRunId}
              />
            )}

            {isRunning && (
              <Card className="p-4">
                <div className="flex items-center gap-3">
                  <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-muted-foreground">Running backtest…</span>
                </div>
              </Card>
            )}

            {error && (
              <Card className="p-4">
                <p className="text-sm text-[--negative]">{error}</p>
              </Card>
            )}

            {result?.status === "insufficient_data" && (
              <Card className="p-4">
                <p className="text-sm text-[--warning]">
                  Insufficient data — need at least 10 analysis recommendations in history to run a
                  backtest.
                </p>
              </Card>
            )}

            {hasResults ? (
              <Tabs defaultValue="performance">
                <div className="flex items-center justify-between mb-3">
                  <TabsList>
                    <TabsTrigger value="performance">Performance</TabsTrigger>
                    <TabsTrigger value="trades">Trade Log</TabsTrigger>
                    <TabsTrigger value="regime">Regime Timeline</TabsTrigger>
                  </TabsList>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => exportCsv(tradeLog)}
                    disabled={tradeLog.length === 0}
                  >
                    <Download size={13} className="mr-1.5" />
                    Export CSV
                  </Button>
                </div>

                <TabsContent value="performance">
                  <PerformanceTab
                    sharpe={sharpe}
                    totalReturn={totalReturn}
                    maxDrawdown={maxDrawdown}
                    alpha={alpha}
                    equityCurve={equityCurve}
                  />
                </TabsContent>

                <TabsContent value="trades">
                  <Card className="p-0 overflow-hidden">
                    <div className="px-3 py-2 border-b border-border flex items-center justify-between">
                      <span className="text-xs font-medium text-foreground">
                        Trade Log ({tradeLog.length})
                      </span>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead>
                          <tr className="border-b border-border">
                            {["Date", "Ticker", "Dir", "Entry", "Exit", "Return", "Regime", ""].map(
                              (h) => (
                                <th
                                  key={h}
                                  className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50"
                                >
                                  {h}
                                </th>
                              ),
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {tradeLog.map((trade, i) => {
                            const normalised = {
                              date: trade.entry_date ?? trade.date ?? "—",
                              ticker: trade.ticker ?? "—",
                              direction: trade.direction ?? (trade.pnl_pct >= 0 ? "LONG" : "LONG"),
                              entry_price: trade.entry_price ?? 0,
                              exit_price: trade.exit_price ?? 0,
                              return_pct: trade.return_pct ?? trade.pnl_pct ?? 0,
                              regime: trade.regime ?? null,
                              signals: trade.signals ?? null,
                              vix_level: trade.vix_level ?? null,
                            };
                            return <TradeDetailRow key={i} trade={normalised} />;
                          })}
                          {tradeLog.length === 0 && (
                            <tr>
                              <td colSpan={8} className="px-3 py-6 text-center text-xs text-muted-foreground">
                                No trades in this run.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </Card>
                </TabsContent>

                <TabsContent value="regime">
                  <Card className="p-8 text-center">
                    <p className="text-sm text-muted-foreground">Coming in Phase B</p>
                  </Card>
                </TabsContent>
              </Tabs>
            ) : (
              !isRunning && !error && (
                <Card className="p-10 flex flex-col items-center gap-4 text-center">
                  <p className="text-sm text-muted-foreground">
                    No in-process backtest results loaded.
                  </p>
                  <Button size="sm" onClick={() => setDialogOpen(true)}>
                    <Plus size={13} className="mr-1.5" />
                    New Backtest
                  </Button>
                </Card>
              )
            )}
          </div>
        </TabsContent>
      </Tabs>

      <NewBacktestDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSubmit={handleSubmit}
        isRunning={isRunning || isModalDispatching}
      />
    </div>
  );
}

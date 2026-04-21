import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ArrowLeft, ChevronRight, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useModalCombinations,
  useModalComboTrades,
  useModalRun,
} from "../hooks/useModalBacktests";
import {
  StatusBadge,
  extractSignalScores,
  formatDate,
  formatNum,
  formatPct,
  shortHash,
  signedClass,
} from "../components/backtest/modal-format";
import type { ModalTrade } from "../api/types";

function exportTradesCsv(runId: string, comboIdx: number, trades: ModalTrade[]) {
  if (trades.length === 0) return;
  const keys = [
    "ticker", "direction", "entry_date", "exit_date",
    "entry_price", "exit_price", "pnl_dollar", "pnl_pct",
    "holding_days", "exit_reason", "composite_score", "regime_at_entry",
  ];
  const header = keys.join(",");
  const rows = trades.map((t) =>
    keys.map((k) => {
      const v = (t as any)[k];
      if (v == null) return "";
      const s = String(v);
      return s.includes(",") || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")
  );
  const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `modal_${shortHash(runId, 8)}_combo_${comboIdx}_trades.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ModalComboDetailPage() {
  const { runId, comboIdx } = useParams<{ runId: string; comboIdx: string }>();
  const navigate = useNavigate();
  const idx = comboIdx != null ? Number(comboIdx) : undefined;

  const { run } = useModalRun(runId);
  // Pull combinations once to show the specific combo's train/test slices.
  const { combinations } = useModalCombinations(runId, {
    active: false,
    pollMs: 0,
    limit: 20000,
  });
  const combo = useMemo(
    () => combinations.find((c) => c.combo_idx === idx),
    [combinations, idx],
  );
  const { trades, isLoading, error } = useModalComboTrades(runId, idx);

  const [filterTicker, setFilterTicker] = useState("");
  const filteredTrades = useMemo(() => {
    if (!filterTicker.trim()) return trades;
    const q = filterTicker.trim().toUpperCase();
    return trades.filter((t) => t.ticker.toUpperCase().includes(q));
  }, [trades, filterTicker]);

  const stats = useMemo(() => {
    if (trades.length === 0) return null;
    const wins = trades.filter((t) => (t.pnl_pct ?? 0) > 0).length;
    const totalPnl = trades.reduce((a, t) => a + (t.pnl_dollar ?? 0), 0);
    const avgPct = trades.reduce((a, t) => a + (t.pnl_pct ?? 0), 0) / trades.length;
    return {
      total: trades.length,
      wins,
      losses: trades.length - wins,
      winRate: trades.length > 0 ? (wins / trades.length) * 100 : 0,
      totalPnl,
      avgPct,
    };
  }, [trades]);

  if (!runId || idx == null) {
    return <p className="text-sm text-muted-foreground">Missing run or combo identifier.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => navigate(`/backtest/modal/runs/${runId}`)}
          >
            <ArrowLeft size={13} className="mr-1.5" />
            Run
          </Button>
          <h1 className="text-lg font-semibold text-foreground">
            Combo <span className="font-mono text-primary">#{idx}</span>
            <span className="text-xs text-muted-foreground ml-2">
              of run <code className="font-mono">{shortHash(runId, 10)}</code>
            </span>
          </h1>
          {run && <StatusBadge status={run.status} />}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => exportTradesCsv(runId, idx, filteredTrades)}
          disabled={filteredTrades.length === 0}
        >
          <Download size={12} className="mr-1.5" />
          Export CSV
        </Button>
      </div>

      {/* Combo summary */}
      {combo && (
        <Card className="p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                OOS Sharpe
              </div>
              <div className={`mt-1 text-sm font-medium ${signedClass(combo.oos_sharpe)}`}>
                {formatNum(combo.oos_sharpe)}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                Return
              </div>
              <div className={`mt-1 text-sm font-medium ${signedClass(combo.return_pct)}`}>
                {formatPct(combo.return_pct)}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                # Trades
              </div>
              <div className="mt-1 text-sm text-foreground">{combo.n_trades ?? "—"}</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                # Test Dates
              </div>
              <div className="mt-1 text-sm text-foreground">{combo.n_test_dates ?? "—"}</div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                Train Groups
              </div>
              <div className="mt-1 text-xs text-muted-foreground font-mono">
                {combo.train_indices?.join(", ") ?? "—"}
              </div>
            </div>
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                Test Groups
              </div>
              <div className="mt-1 text-xs text-muted-foreground font-mono">
                {combo.test_indices?.join(", ") ?? "—"}
              </div>
            </div>
          </div>
          {combo.gates_json && Object.keys(combo.gates_json).length > 0 && (
            <div className="mt-4 pt-3 border-t border-border">
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50 mb-2">
                Gates
              </div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(combo.gates_json)
                  .filter(([, v]) => typeof v === "boolean")
                  .map(([k, v]) => (
                    <Badge
                      key={k}
                      variant="outline"
                      className={cn(
                        "text-[9px]",
                        v
                          ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
                          : "text-[--negative] border-[--negative]/20 bg-[--negative]/10"
                      )}
                    >
                      {k}: {String(v)}
                    </Badge>
                  ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Trade stats */}
      {stats && (
        <Card className="p-4">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <StatBox label="Total Trades" value={String(stats.total)} />
            <StatBox
              label="Win Rate"
              value={`${stats.winRate.toFixed(1)}%`}
              sub={`${stats.wins}W / ${stats.losses}L`}
            />
            <StatBox
              label="Avg PnL %"
              value={formatPct(stats.avgPct)}
              className={signedClass(stats.avgPct)}
            />
            <StatBox
              label="Total $ PnL"
              value={`$${stats.totalPnl.toFixed(0)}`}
              className={signedClass(stats.totalPnl)}
            />
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                Filter by Ticker
              </label>
              <input
                type="text"
                value={filterTicker}
                onChange={(e) => setFilterTicker(e.target.value)}
                placeholder="e.g. AAPL"
                className="mt-1 w-full bg-secondary border border-border rounded-md px-2 py-1 text-xs text-foreground"
              />
            </div>
          </div>
        </Card>
      )}

      {/* Trade log */}
      {error && (
        <Card className="p-3">
          <p className="text-xs text-[--negative]">{error}</p>
        </Card>
      )}

      <Card className="p-0 overflow-hidden">
        <div className="px-3 py-2 border-b border-border flex items-center justify-between">
          <span className="text-xs font-medium text-foreground">
            Trade Log ({filteredTrades.length})
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                {[
                  "Entry", "Exit", "Ticker", "Dir", "Entry $", "Exit $",
                  "PnL %", "PnL $", "Hold", "Reason", "Regime", "",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredTrades.map((t, i) => (
                <TradeRow
                  key={`${t.ticker}-${t.entry_date}-${i}`}
                  trade={t}
                  tickerLink={t.ticker ? `/stock/${t.ticker}` : undefined}
                />
              ))}
              {!isLoading && filteredTrades.length === 0 && (
                <tr>
                  <td colSpan={12} className="px-3 py-8 text-center text-xs text-muted-foreground">
                    {trades.length === 0 ? "No trades in this combination." : "No trades match filter."}
                  </td>
                </tr>
              )}
              {isLoading && trades.length === 0 && (
                <tr>
                  <td colSpan={12} className="px-3 py-8 text-center text-xs text-muted-foreground">
                    Loading trades…
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

function StatBox({
  label,
  value,
  sub,
  className,
}: {
  label: string;
  value: string;
  sub?: string;
  className?: string;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
        {label}
      </div>
      <div className={cn("mt-1 text-sm font-medium", className ?? "text-foreground")}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{sub}</div>}
    </div>
  );
}

function TradeRow({ trade, tickerLink }: { trade: ModalTrade; tickerLink?: string }) {
  const [open, setOpen] = useState(false);
  const signals = useMemo(
    () => extractSignalScores(trade.signals_at_entry_json),
    [trade.signals_at_entry_json],
  );
  const hasSignals = signals.length > 0;
  const flags: string[] = useMemo(() => {
    const f = (trade.signals_at_entry_json as any)?.flags;
    return Array.isArray(f) ? f : [];
  }, [trade.signals_at_entry_json]);

  return (
    <>
      <tr
        className={cn(
          "border-b border-border/40 transition-colors",
          hasSignals ? "cursor-pointer hover:bg-secondary/40" : "",
        )}
        onClick={() => hasSignals && setOpen((v) => !v)}
      >
        <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
          {formatDate(trade.entry_date)}
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
          {formatDate(trade.exit_date)}
        </td>
        <td className="px-3 py-2 text-xs font-medium text-foreground">
          {tickerLink ? (
            <Link
              to={tickerLink}
              onClick={(e) => e.stopPropagation()}
              className="hover:text-primary transition-colors"
            >
              {trade.ticker}
            </Link>
          ) : (
            trade.ticker
          )}
        </td>
        <td className="px-3 py-2">
          <Badge
            variant="outline"
            className={cn(
              "text-[9px]",
              trade.direction === "LONG"
                ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
                : "text-[--negative] border-[--negative]/20 bg-[--negative]/10",
            )}
          >
            {trade.direction}
          </Badge>
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">
          {trade.entry_price != null ? `$${trade.entry_price.toFixed(2)}` : "—"}
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">
          {trade.exit_price != null ? `$${trade.exit_price.toFixed(2)}` : "—"}
        </td>
        <td className={`px-3 py-2 text-xs font-medium ${signedClass(trade.pnl_pct)}`}>
          {formatPct(trade.pnl_pct)}
        </td>
        <td className={`px-3 py-2 text-xs ${signedClass(trade.pnl_dollar)}`}>
          {trade.pnl_dollar != null ? `$${trade.pnl_dollar.toFixed(0)}` : "—"}
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">{trade.holding_days ?? "—"}d</td>
        <td className="px-3 py-2 text-[10px] text-muted-foreground">{trade.exit_reason ?? "—"}</td>
        <td className="px-3 py-2 text-[10px] text-muted-foreground">{trade.regime_at_entry ?? "—"}</td>
        <td className="px-3 py-2">
          {hasSignals && (
            <ChevronRight
              size={12}
              className={cn(
                "text-muted-foreground transition-transform",
                open && "rotate-90",
              )}
            />
          )}
        </td>
      </tr>
      {open && hasSignals && (
        <tr>
          <td colSpan={12} className="px-3 py-3 bg-card border-b border-border">
            <div className="space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50">
                Signal Scores at Entry
              </div>
              <div className="flex flex-wrap gap-2">
                {[...signals]
                  .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
                  .map(([name, score]) => (
                    <div key={name} className="rounded bg-secondary/40 px-2 py-1">
                      <div className="text-[9px] uppercase tracking-wider text-muted-foreground/60">
                        {name}
                      </div>
                      <div
                        className={cn(
                          "text-xs font-medium",
                          score > 0
                            ? "text-[--positive]"
                            : score < 0
                            ? "text-[--negative]"
                            : "text-muted-foreground",
                        )}
                      >
                        {score > 0 ? "+" : ""}
                        {score.toFixed(3)}
                      </div>
                    </div>
                  ))}
              </div>
              {flags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
                    Flags:
                  </span>
                  {flags.map((f) => (
                    <Badge
                      key={f}
                      variant="outline"
                      className="text-[9px] text-[--warning] border-[--warning]/20 bg-[--warning]/10"
                    >
                      {f}
                    </Badge>
                  ))}
                </div>
              )}
              {trade.composite_score != null && (
                <div className="text-[10px] text-muted-foreground pt-1">
                  Composite score:{" "}
                  <span className={cn("font-medium", signedClass(trade.composite_score))}>
                    {trade.composite_score.toFixed(3)}
                  </span>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

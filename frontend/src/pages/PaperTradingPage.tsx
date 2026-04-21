import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PaperMetricsPanel } from "../components/paper-trading/PaperMetricsPanel";
import { OpenPositionsTable } from "../components/paper-trading/OpenPositionsTable";
import { ClosedTradesTable } from "../components/paper-trading/ClosedTradesTable";
import { AccountPanel } from "../components/paper-trading/AccountPanel";
import { OrderHistoryTable } from "../components/paper-trading/OrderHistoryTable";
import { EquityCurveChart } from "../components/charts/EquityCurveChart";
import { usePaperTrading } from "../hooks/usePaperTrading";
import { Plus, X, RefreshCw } from "lucide-react";

export function PaperTradingPage() {
  const { openPositions, closedTrades, equityCurve, metrics, account, orders, isLoading, isRebalancing, addPosition, closePosition, triggerRebalance } = usePaperTrading();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ ticker: "", entry_price: "", verdict: "BUY" });

  const handleAdd = () => {
    const price = parseFloat(form.entry_price);
    if (!form.ticker.trim() || isNaN(price)) return;
    addPosition({
      ticker: form.ticker.toUpperCase(),
      entry_price: price,
      verdict: form.verdict,
    });
    setForm({ ticker: "", entry_price: "", verdict: "BUY" });
    setShowAdd(false);
  };

  if (isLoading) {
    return (
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        <h1 className="text-lg font-semibold text-foreground">Paper Trading</h1>
        {[1, 2].map((i) => (
          <div key={i} className="rounded-xl border bg-card h-32 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-foreground">Paper Trading</h1>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => triggerRebalance()} disabled={isRebalancing}>
            <RefreshCw size={13} className={`mr-1.5 ${isRebalancing ? "animate-spin" : ""}`} />
            {isRebalancing ? "Rebalancing…" : "Rebalance"}
          </Button>
          <Button size="sm" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? (
              <><X size={13} className="mr-1.5" />Cancel</>
            ) : (
              <><Plus size={13} className="mr-1.5" />Add Position</>
            )}
          </Button>
        </div>
      </div>

      {/* Add position form */}
      {showAdd && (
        <Card className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
            <div>
              <label className="block text-[10px] uppercase tracking-wider font-medium text-muted-foreground mb-1">
                Ticker
              </label>
              <Input
                value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
                placeholder="AAPL"
                className="h-8 text-sm"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider font-medium text-muted-foreground mb-1">
                Entry Price
              </label>
              <Input
                value={form.entry_price}
                onChange={(e) => setForm({ ...form, entry_price: e.target.value })}
                placeholder="150.00"
                className="h-8 text-sm"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider font-medium text-muted-foreground mb-1">
                Verdict
              </label>
              <select
                value={form.verdict}
                onChange={(e) => setForm({ ...form, verdict: e.target.value })}
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-foreground"
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
                <option value="HOLD">HOLD</option>
              </select>
            </div>
            <Button onClick={handleAdd} size="sm" className="h-8">
              Add
            </Button>
          </div>
        </Card>
      )}

      {/* Alpaca account */}
      <AccountPanel account={account} />

      {/* Metrics */}
      <PaperMetricsPanel metrics={metrics} />

      {/* Equity curve */}
      {equityCurve.length > 0 && (
        <Card className="p-3">
          <div className="text-xs font-medium text-muted-foreground mb-3">Equity Curve</div>
          <EquityCurveChart data={equityCurve} />
        </Card>
      )}

      {/* Tables */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card className="p-0 overflow-hidden">
          <OpenPositionsTable positions={openPositions} onClose={closePosition} />
        </Card>
        <Card className="p-0 overflow-hidden">
          <ClosedTradesTable trades={closedTrades} />
        </Card>
      </div>

      {/* Alpaca order history */}
      {orders.length > 0 && (
        <Card className="p-0 overflow-hidden">
          <OrderHistoryTable orders={orders} />
        </Card>
      )}
    </div>
  );
}

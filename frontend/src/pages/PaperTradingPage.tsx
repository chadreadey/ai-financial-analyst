import { useState } from "react";
import { Card } from "../components/common/Card";
import { PaperMetricsPanel } from "../components/paper-trading/PaperMetricsPanel";
import { OpenPositionsTable } from "../components/paper-trading/OpenPositionsTable";
import { ClosedTradesTable } from "../components/paper-trading/ClosedTradesTable";
import { EquityCurveChart } from "../components/charts/EquityCurveChart";
import { usePaperTrading } from "../hooks/usePaperTrading";

export function PaperTradingPage() {
  const { openPositions, closedTrades, equityCurve, metrics, isLoading, addPosition, closePosition } = usePaperTrading();
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

  const inputStyle = {
    background: "var(--bg-primary)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  if (isLoading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>Paper Trading</h1>
        {[1, 2].map((i) => (
          <div key={i} className="rounded-lg h-32 animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>Paper Trading</h1>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="px-3 py-1.5 rounded text-sm font-medium"
          style={{ background: "var(--accent-blue)", color: "white" }}
        >
          {showAdd ? "Cancel" : "Add Position"}
        </button>
      </div>

      {showAdd && (
        <Card>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>Ticker</label>
              <input
                value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
                placeholder="AAPL"
                className="w-full rounded px-3 py-1.5 text-sm"
                style={inputStyle}
              />
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>Entry Price</label>
              <input
                value={form.entry_price}
                onChange={(e) => setForm({ ...form, entry_price: e.target.value })}
                placeholder="150.00"
                className="w-full rounded px-3 py-1.5 text-sm"
                style={inputStyle}
              />
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>Verdict</label>
              <select
                value={form.verdict}
                onChange={(e) => setForm({ ...form, verdict: e.target.value })}
                className="w-full rounded px-3 py-1.5 text-sm"
                style={inputStyle}
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
                <option value="HOLD">HOLD</option>
              </select>
            </div>
            <button
              onClick={handleAdd}
              className="px-4 py-1.5 rounded text-sm font-medium"
              style={{ background: "var(--accent-green)", color: "white" }}
            >
              Add
            </button>
          </div>
        </Card>
      )}

      <PaperMetricsPanel metrics={metrics} />

      {equityCurve.length > 0 && (
        <Card>
          <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
            Paper Trading Equity Curve
          </h3>
          <EquityCurveChart data={equityCurve} />
        </Card>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <OpenPositionsTable positions={openPositions} onClose={closePosition} />
        </Card>
        <Card>
          <ClosedTradesTable trades={closedTrades} />
        </Card>
      </div>
    </div>
  );
}

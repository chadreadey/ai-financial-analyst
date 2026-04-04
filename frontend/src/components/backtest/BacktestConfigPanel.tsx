import { useState } from "react";
import { Card } from "../common/Card";

interface Props {
  onSubmit: (config: { tickers: string[]; start_date: string; end_date: string }) => void;
  isRunning: boolean;
}

export function BacktestConfigPanel({ onSubmit, isRunning }: Props) {
  const [tickers, setTickers] = useState("");
  const [startDate, setStartDate] = useState("2022-01-01");
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));

  const handleSubmit = () => {
    const tickerList = tickers.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean);
    if (tickerList.length === 0) return;
    onSubmit({ tickers: tickerList, start_date: startDate, end_date: endDate });
  };

  const inputStyle = {
    background: "var(--bg-primary)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  return (
    <Card>
      <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
        Backtest Configuration
      </h3>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>Tickers (comma-separated)</label>
          <input
            value={tickers}
            onChange={(e) => setTickers(e.target.value.toUpperCase())}
            placeholder="AAPL, MSFT, NVDA"
            className="w-full rounded px-3 py-1.5 text-sm"
            style={inputStyle}
          />
        </div>
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-full rounded px-3 py-1.5 text-sm"
            style={inputStyle}
          />
        </div>
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--text-muted)" }}>End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="w-full rounded px-3 py-1.5 text-sm"
            style={inputStyle}
          />
        </div>
      </div>
      <button
        onClick={handleSubmit}
        disabled={isRunning}
        className="px-4 py-2 rounded text-sm font-medium"
        style={{
          background: isRunning ? "var(--bg-hover)" : "var(--accent-blue)",
          color: isRunning ? "var(--text-muted)" : "white",
          cursor: isRunning ? "not-allowed" : "pointer",
        }}
      >
        {isRunning ? "Running..." : "Run Backtest"}
      </button>
    </Card>
  );
}

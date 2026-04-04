import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { Card } from "../components/common/Card";
import { Badge } from "../components/common/Badge";
import { api } from "../api/client";
import type { PortfolioSummary } from "../api/types";

const COLORS = [
  "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
];

export function PortfolioPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [ticker, setTicker] = useState("");
  const [shares, setShares] = useState("");
  const [costBasis, setCostBasis] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = () => {
    setLoading(true);
    api.getPortfolio()
      .then(setSummary)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { refresh(); }, []);

  const addHolding = async () => {
    if (!ticker.trim() || !shares || !costBasis) return;
    await api.upsertHolding({
      ticker: ticker.trim().toUpperCase(),
      shares: parseFloat(shares),
      cost_basis: parseFloat(costBasis),
      date_added: new Date().toISOString().slice(0, 10),
    });
    setTicker("");
    setShares("");
    setCostBasis("");
    refresh();
  };

  const removeHolding = async (t: string) => {
    await api.deleteHolding(t);
    refresh();
  };

  const inputStyle = {
    background: "var(--bg-primary)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  const holdings = summary?.holdings ?? [];
  const allocData = Object.entries(summary?.allocations ?? {}).map(([name, value]) => ({
    name,
    value,
  }));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
        Portfolio
      </h1>

      {summary && holdings.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-[1fr_300px] gap-4">
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>Total Value</div>
              <div className="text-xl font-bold mt-1" style={{ color: "var(--text-primary)" }}>
                ${summary.total_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </Card>
            <Card>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>Total Cost</div>
              <div className="text-xl font-bold mt-1" style={{ color: "var(--text-primary)" }}>
                ${summary.total_cost.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </Card>
            <Card>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>P&L</div>
              <div
                className="text-xl font-bold mt-1"
                style={{
                  color: summary.day_change_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)",
                }}
              >
                {summary.day_change_pct >= 0 ? "+" : ""}{summary.day_change_pct}%
              </div>
            </Card>
          </div>

          {allocData.length > 0 && (
            <Card>
              <div className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>Allocation</div>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie
                    data={allocData}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={70}
                    dataKey="value"
                    stroke="none"
                  >
                    {allocData.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      color: "var(--text-primary)",
                      fontSize: 12,
                    }}
                    formatter={(value) => `${value}%`}
                  />
                </PieChart>
              </ResponsiveContainer>
            </Card>
          )}
        </div>
      )}

      <Card>
        <h3 className="font-semibold text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
          Add Position
        </h3>
        <div className="flex gap-3 items-end flex-wrap">
          <div>
            <label className="text-xs block mb-1" style={{ color: "var(--text-muted)" }}>Ticker</label>
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              className="rounded px-2 py-1.5 text-sm w-24"
              style={inputStyle}
              placeholder="AAPL"
            />
          </div>
          <div>
            <label className="text-xs block mb-1" style={{ color: "var(--text-muted)" }}>Shares</label>
            <input
              value={shares}
              onChange={(e) => setShares(e.target.value)}
              type="number"
              className="rounded px-2 py-1.5 text-sm w-24"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="text-xs block mb-1" style={{ color: "var(--text-muted)" }}>Cost Basis</label>
            <input
              value={costBasis}
              onChange={(e) => setCostBasis(e.target.value)}
              type="number"
              className="rounded px-2 py-1.5 text-sm w-28"
              style={inputStyle}
              placeholder="150.00"
            />
          </div>
          <button
            onClick={addHolding}
            className="px-4 py-1.5 rounded text-sm font-medium"
            style={{ background: "var(--accent-blue)", color: "white" }}
          >
            Add
          </button>
        </div>
      </Card>

      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Ticker", "Shares", "Cost Basis", "Total Cost", "Allocation", ""].map((h) => (
                <th
                  key={h}
                  className="text-left px-3 py-2 font-semibold"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {holdings.map((h) => (
              <tr
                key={h.ticker}
                className="cursor-pointer hover:opacity-80 transition-opacity"
                style={{ borderBottom: "1px solid var(--border)" }}
              >
                <td
                  className="px-3 py-2 font-medium"
                  style={{ color: "var(--accent-blue)" }}
                  onClick={() => navigate(`/analysis?ticker=${h.ticker}`)}
                >
                  {h.ticker}
                </td>
                <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                  {h.shares}
                </td>
                <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                  ${h.cost_basis.toFixed(2)}
                </td>
                <td className="px-3 py-2" style={{ color: "var(--text-primary)" }}>
                  ${(h.shares * h.cost_basis).toFixed(2)}
                </td>
                <td className="px-3 py-2">
                  {summary?.allocations[h.ticker] != null && (
                    <Badge label={`${summary.allocations[h.ticker]}%`} variant="blue" />
                  )}
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={(e) => { e.stopPropagation(); removeHolding(h.ticker); }}
                    className="text-xs"
                    style={{ color: "var(--accent-red)" }}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {holdings.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center" style={{ color: "var(--text-muted)" }}>
                  {loading ? "Loading..." : "No holdings yet. Add your first position above."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

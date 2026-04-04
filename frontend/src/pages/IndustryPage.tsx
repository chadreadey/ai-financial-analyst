import { useState, useEffect } from "react";
import { Card } from "../components/common/Card";
import { Badge } from "../components/common/Badge";
import { api } from "../api/client";
import type { SectorOverview } from "../api/types";
import { TrendingUp, ArrowLeft, Filter } from "lucide-react";

const STRATEGY_PRESETS = [
  { label: "Value", description: "Low P/E, high dividend yield companies" },
  { label: "Growth", description: "High revenue growth, strong momentum" },
  { label: "Dividend Income", description: "Consistent dividend payers, stable cash flows" },
  { label: "Defensive", description: "Low-beta, recession-resistant sectors" },
];

export function IndustryPage() {
  const [sectors, setSectors] = useState<SectorOverview[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getSectors()
      .then((d) => setSectors(d.sectors))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (selected) {
    const sector = sectors.find((s) => s.sector === selected);
    return (
      <div className="space-y-6">
        <button
          onClick={() => setSelected(null)}
          className="flex items-center gap-2 text-sm"
          style={{ color: "var(--accent-blue)" }}
        >
          <ArrowLeft size={16} /> Back to sectors
        </button>

        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
            {selected}
          </h1>
          {sector?.etf_symbol && <Badge label={sector.etf_symbol} variant="blue" />}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card>
            <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>
              Sector ETF
            </h3>
            <div className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
              {sector?.etf_symbol || "N/A"}
            </div>
            {sector?.ytd_return_pct !== null && sector?.ytd_return_pct !== undefined && (
              <div
                className="text-sm mt-1"
                style={{ color: sector.ytd_return_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}
              >
                {sector.ytd_return_pct >= 0 ? "+" : ""}{sector.ytd_return_pct.toFixed(1)}% YTD
              </div>
            )}
          </Card>
          <Card>
            <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>
              Peer Comparison
            </h3>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              Run a sector analysis to see peer comparisons, specialist briefings, and research insights.
            </p>
            <button
              className="mt-3 px-4 py-1.5 rounded text-sm font-medium"
              style={{ background: "var(--accent-blue)", color: "white" }}
              onClick={() => {}}
            >
              Analyze Sector
            </button>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
        Industry Overview
      </h1>

      <div>
        <div className="flex items-center gap-2 mb-3">
          <Filter size={14} style={{ color: "var(--text-muted)" }} />
          <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
            Strategy Presets
          </span>
        </div>
        <div className="flex gap-2 flex-wrap">
          {STRATEGY_PRESETS.map((s) => (
            <button
              key={s.label}
              className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
              style={{
                background: "var(--bg-card)",
                color: "var(--text-secondary)",
                border: "1px solid var(--border)",
              }}
              title={s.description}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {loading ? (
          <Card className="col-span-full">
            <p className="text-center py-8" style={{ color: "var(--text-muted)" }}>
              Loading sectors...
            </p>
          </Card>
        ) : sectors.length === 0 ? (
          <Card className="col-span-full">
            <p className="text-center py-8" style={{ color: "var(--text-muted)" }}>
              No sector data available.
            </p>
          </Card>
        ) : (
          sectors.map((s) => (
            <Card
              key={s.sector}
              className="hover:opacity-90 transition-opacity cursor-pointer"
            >
              <div onClick={() => setSelected(s.sector)}>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-semibold text-sm" style={{ color: "var(--text-primary)" }}>
                    {s.sector}
                  </h3>
                  <TrendingUp size={16} style={{ color: "var(--accent-green)" }} />
                </div>
                <div className="flex items-center gap-2">
                  <Badge label={s.etf_symbol} variant="blue" />
                  {s.ytd_return_pct !== null && s.ytd_return_pct !== undefined && (
                    <span
                      className="text-xs font-medium"
                      style={{ color: s.ytd_return_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}
                    >
                      {s.ytd_return_pct >= 0 ? "+" : ""}{s.ytd_return_pct.toFixed(1)}% YTD
                    </span>
                  )}
                </div>
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}

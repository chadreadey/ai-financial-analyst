import { useState } from "react";
import { PriceChart } from "../charts/PriceChart";
import { usePriceHistory } from "../../hooks/usePriceHistory";
import { useRecommendationHistory } from "../../hooks/useRecommendationHistory";

const PERIODS = ["1mo", "3mo", "1yr", "3yr", "5yr"] as const;

interface Props {
  ticker: string;
}

export function PriceHistoryTab({ ticker }: Props) {
  const [period, setPeriod] = useState<string>("1yr");
  const { bars, isLoading } = usePriceHistory(ticker, period);
  const { records } = useRecommendationHistory(ticker);

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className="px-3 py-1 rounded-full text-xs font-medium transition-colors"
            style={{
              background: period === p ? "var(--accent-blue)" : "var(--bg-hover)",
              color: period === p ? "white" : "var(--text-secondary)",
            }}
          >
            {p}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div
          className="rounded animate-pulse"
          style={{ height: 400, background: "var(--bg-primary)" }}
        />
      ) : bars.length > 0 ? (
        <PriceChart bars={bars} recommendations={records} />
      ) : (
        <div
          className="rounded flex items-center justify-center"
          style={{ height: 400, background: "var(--bg-primary)", color: "var(--text-muted)" }}
        >
          No price data available
        </div>
      )}
    </div>
  );
}

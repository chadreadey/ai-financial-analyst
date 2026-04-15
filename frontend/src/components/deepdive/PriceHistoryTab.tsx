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
            className={[
              "px-3 py-1 rounded-full text-xs font-medium transition-colors",
              period === p
                ? "bg-primary text-primary-foreground"
                : "bg-secondary text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {p}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="rounded animate-pulse bg-background" style={{ height: 400 }} />
      ) : bars.length > 0 ? (
        <PriceChart bars={bars} recommendations={records} />
      ) : (
        <div
          className="rounded flex items-center justify-center bg-background text-muted-foreground"
          style={{ height: 400 }}
        >
          No price data available
        </div>
      )}
    </div>
  );
}

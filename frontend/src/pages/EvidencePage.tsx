import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  SERIES_NAMES,
  fetchEvidence,
  formatDelta,
  yearTicks,
  type EvidencePayload,
  type SeriesName,
} from "@/lib/evidence";

const DISCLAIMER = "Research demo, not investment advice.";

// AI-augmented is the series under discussion, so it gets the primary accent.
const SERIES_STYLE: Record<SeriesName, { stroke: string; dash?: string; width: number }> = {
  SPY: { stroke: "hsl(var(--muted-foreground))", dash: "5 4", width: 1.5 },
  "Quant-only": { stroke: "var(--positive)", width: 1.5 },
  "AI-augmented": { stroke: "hsl(var(--primary))", width: 2.5 },
};

const money = (v: number) => `$${Number(v.toFixed(2))}`;
const pct = (v: number) => `${v.toFixed(1)}%`;

export function EvidencePage() {
  const [data, setData] = useState<EvidencePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEvidence()
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Adding the LLM agents made the backtest worse.</h1>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!data && !error && <p className="text-sm text-muted-foreground">Loading...</p>}

      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[480px] text-sm">
              <caption className="sr-only">Backtest metrics by series, 2018–2025</caption>
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="p-3 font-medium">Series</th>
                  <th className="p-3 font-medium">Sharpe</th>
                  <th className="p-3 font-medium">Sortino</th>
                  <th className="p-3 font-medium">Annual return</th>
                  <th className="p-3 font-medium">Max drawdown</th>
                </tr>
              </thead>
              <tbody>
                {SERIES_NAMES.map((name) => {
                  const s = data.series[name];
                  return (
                    <tr
                      key={name}
                      className={`border-t border-border ${name === "AI-augmented" ? "font-semibold" : ""}`}
                    >
                      <th scope="row" className="p-3 text-left">
                        {name}
                      </th>
                      <td className="p-3">{s.sharpe.toFixed(2)}</td>
                      <td className="p-3">{s.sortino.toFixed(2)}</td>
                      <td className="p-3">{pct(s.ann_return_pct)}</td>
                      <td className="p-3">{pct(s.max_dd_pct)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="text-sm text-muted-foreground">
            Sharpe: Quant-only {formatDelta(data.series["Quant-only"].sharpe, data.series.SPY.sharpe)} vs
            SPY · AI-augmented{" "}
            {formatDelta(data.series["AI-augmented"].sharpe, data.series["Quant-only"].sharpe)} vs
            Quant-only
          </p>

          <section aria-label="Growth of $1, log scale">
            <h2 className="mb-2 text-sm font-medium text-muted-foreground">
              Growth of $1 (log scale)
            </h2>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={data.curve}>
                <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={(d: string) => d.slice(0, 4)}
                  ticks={yearTicks(data.curve)}
                  interval={0}
                />
                <YAxis
                  scale="log"
                  domain={["auto", "auto"]}
                  tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={money}
                  width={44}
                />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    color: "hsl(var(--foreground))",
                    fontSize: 12,
                  }}
                  formatter={(v: unknown) => money(v as number)}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {SERIES_NAMES.map((name) => (
                  <Line
                    key={name}
                    type="monotone"
                    dataKey={name}
                    stroke={SERIES_STYLE[name].stroke}
                    strokeDasharray={SERIES_STYLE[name].dash}
                    strokeWidth={SERIES_STYLE[name].width}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </section>
        </>
      )}

      <p className="text-sm leading-relaxed">
        In a 2018–2025 backtest (10 positions), the quantitative screen alone had a Sharpe ratio of
        1.15 against 0.74 for SPY; adding the LLM agents lowered it to 1.01. Survivorship bias and
        LLM look-ahead are not corrected, so treat these as upper bounds.
      </p>

      <section>
        <h2 className="mb-2 text-lg font-semibold">What this means for the app</h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          The agents are shown here as a research and explanation layer, not as the source of
          returns. {DISCLAIMER}
        </p>
      </section>
    </div>
  );
}

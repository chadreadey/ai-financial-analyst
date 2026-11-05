import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import { fetchEvidence, formatDelta, type EvidencePayload } from "@/lib/evidence";

const SIGNALS = [
  "Quality (QMJ)",
  "Earnings surprise (SUE)",
  "Revision momentum (ERM)",
  "OBV trend",
  "Insider MSPR",
  "Institutional flow",
];

const PIPELINE = [
  "Walk-forward backtest, monthly rebalance",
  "VIX regime filter",
  "Combinatorial purged cross-validation",
  "Per-signal IC with HAC t-stats",
];

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-md border border-border bg-background/60 p-3">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-bold tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground tabular-nums">{sub}</div>
    </div>
  );
}

/**
 * Surfaces the quantitative screen that sits underneath the LLM briefs. The
 * briefs are an explanation layer; the backtested returns come from here.
 */
export function QuantEnginePanel() {
  const [data, setData] = useState<EvidencePayload | null>(null);

  useEffect(() => {
    fetchEvidence()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const quant = data?.series["Quant-only"];
  const spy = data?.series.SPY;
  const years = data
    ? `${data.curve[0]?.date.slice(0, 4)}–${data.curve[data.curve.length - 1]?.date.slice(0, 4)}`
    : null;

  return (
    <section
      aria-labelledby="quant-engine-heading"
      className="rounded-lg border border-border bg-card p-5 sm:p-6 space-y-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--positive)]">
            Quant engine · separate from the LLM layer
          </div>
          <h2 id="quant-engine-heading" className="text-lg font-semibold tracking-tight">
            The returns come from the screen, not the agents
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            A signal stack ranks the universe and picks {data ? data.config.n_positions : "ten"}{" "}
            names a month. The agents above explain a ticker; they do not drive the backtest.
          </p>
        </div>
        <Link to="/evidence" className="text-sm text-primary underline-offset-4 hover:underline">
          Full results →
        </Link>
      </div>

      {data && quant && spy && (
        <div className="grid gap-4 md:grid-cols-[1fr_minmax(0,220px)] md:items-stretch">
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="Sharpe"
              value={quant.sharpe.toFixed(2)}
              sub={`${formatDelta(quant.sharpe, spy.sharpe)} vs SPY ${spy.sharpe.toFixed(2)}`}
            />
            <Stat
              label="Annual return"
              value={`${quant.ann_return_pct.toFixed(1)}%`}
              sub={`SPY ${spy.ann_return_pct.toFixed(1)}%`}
            />
            <Stat
              label="Growth of $1"
              value={`$${(1 + quant.total_return_pct / 100).toFixed(2)}`}
              sub={`SPY $${(1 + spy.total_return_pct / 100).toFixed(2)} · ${years}`}
            />
          </div>
          <figure className="rounded-md border border-border bg-background/60 p-3 flex flex-col">
            <figcaption className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Growth of $1, log scale
            </figcaption>
            <div className="mt-2 flex-1 min-h-[72px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.curve} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
                  <YAxis hide scale="log" domain={["auto", "auto"]} />
                  <Line
                    type="monotone"
                    dataKey="SPY"
                    stroke="hsl(var(--muted-foreground))"
                    strokeDasharray="4 3"
                    strokeWidth={1.25}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="Quant-only"
                    stroke="var(--positive)"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex gap-3 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <span className="inline-block h-0.5 w-3 bg-[var(--positive)]" /> Quant screen
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="inline-block w-3 border-t border-dashed border-muted-foreground" />{" "}
                SPY
              </span>
            </div>
          </figure>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 text-sm">
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground">
            Signals
          </div>
          <ul className="flex flex-wrap gap-1.5">
            {SIGNALS.map((s) => (
              <li
                key={s}
                className="rounded-full border border-border px-2 py-0.5 text-xs text-foreground/90"
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground">
            Validation
          </div>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {PIPELINE.map((p) => (
              <li key={p} className="flex gap-2">
                <span className="text-[var(--positive)]">•</span>
                {p}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Survivorship bias and look-ahead are not corrected; treat the numbers as upper bounds.
      </p>
    </section>
  );
}

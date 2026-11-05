import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { QuantEnginePanel } from "@/components/public/QuantEnginePanel";
import { TickerForm } from "@/components/public/TickerForm";
import { fetchShowcaseIndex, formatCompanyName, type ShowcaseIndexEntry } from "@/lib/showcase";

const PITCH =
  "Enter a ticker; six LLM analyst agents work in parallel and a synthesis agent reconciles them into one investment brief. A separate quant engine ranks the universe and is what gets backtested.";

export function HomePage() {
  const [examples, setExamples] = useState<ShowcaseIndexEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchShowcaseIndex()
      .then(setExamples)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">AI Financial Analyst</h1>
        <p className="max-w-2xl text-muted-foreground">{PITCH}</p>
        <TickerForm examples={examples} loading={loading} error={error} />
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Example briefs
          </h2>
          <span className="text-xs text-muted-foreground">
            LLM layer · cached runs, no live API call
          </span>
        </div>
        {loading && <p className="text-sm text-muted-foreground">Loading examples...</p>}
        {error && <p className="text-sm text-muted-foreground">{error}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          {examples.map((x) => (
            <Link
              key={x.ticker}
              to={`/brief/${x.ticker}`}
              className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-lg font-bold">{x.ticker}</div>
                  <div className="truncate text-xs text-muted-foreground">
                    {formatCompanyName(x.company_name)}
                  </div>
                </div>
                <span className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
                  {x.verdict}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
                {x.price_target != null && (
                  <span className="text-muted-foreground">
                    Target <span className="text-foreground">${x.price_target.toFixed(2)}</span>
                  </span>
                )}
                {x.has_conflicts && (
                  <span className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                    Agents disagree
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      </section>

      <QuantEnginePanel />
    </div>
  );
}

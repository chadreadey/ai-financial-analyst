import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  fetchShowcaseIndex,
  formatCompanyName,
  resolveTickerRoute,
  type ShowcaseIndexEntry,
} from "@/lib/showcase";

const PITCH =
  "Enter a ticker; six LLM analyst agents work in parallel and a synthesis agent reconciles them into one investment brief.";

export function HomePage() {
  const navigate = useNavigate();
  const [ticker, setTicker] = useState("");
  const [examples, setExamples] = useState<ShowcaseIndexEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchShowcaseIndex()
      .then(setExamples)
      .catch((e: Error) => setError(e.message));
  }, []);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!ticker.trim()) return;
    navigate(
      resolveTickerRoute(
        ticker,
        examples.map((x) => x.ticker)
      )
    );
  };

  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">AI Financial Analyst</h1>
        <p className="max-w-2xl text-muted-foreground">{PITCH}</p>
        <form onSubmit={onSubmit} className="flex gap-2 max-w-md">
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="Ticker, e.g. NVDA"
            aria-label="Ticker"
            autoCapitalize="characters"
            className="flex-1 min-w-0 rounded-md border border-border bg-secondary px-3 py-2 text-sm uppercase placeholder:normal-case focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            type="submit"
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            Analyze
          </button>
        </form>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Example briefs
        </h2>
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
    </div>
  );
}

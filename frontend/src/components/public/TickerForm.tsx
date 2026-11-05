import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  EXAMPLE_TICKERS,
  fetchShowcaseIndex,
  resolveTickerRoute,
  type ShowcaseIndexEntry,
} from "@/lib/showcase";

interface Props {
  /** Pre-fetched example index; when omitted the form loads it itself. */
  examples?: ShowcaseIndexEntry[];
  loading?: boolean;
  error?: string | null;
  autoFocus?: boolean;
}

/**
 * Ticker entry shared by the home page and the Analyze page. Known example
 * tickers route to their cached brief; anything else starts a live run.
 */
export function TickerForm({ examples, loading, error, autoFocus }: Props) {
  const navigate = useNavigate();
  const [ticker, setTicker] = useState("");
  const selfManaged = examples === undefined;
  const [own, setOwn] = useState<{
    examples: ShowcaseIndexEntry[];
    loading: boolean;
    error: string | null;
  }>({ examples: [], loading: selfManaged, error: null });

  useEffect(() => {
    if (!selfManaged) return;
    fetchShowcaseIndex()
      .then((x) => setOwn({ examples: x, loading: false, error: null }))
      .catch((e: Error) => setOwn({ examples: [], loading: false, error: e.message }));
  }, [selfManaged]);

  const list = selfManaged ? own.examples : examples;
  const isLoading = selfManaged ? own.loading : Boolean(loading);
  const err = selfManaged ? own.error : error;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading || !ticker.trim()) return;
    const known = err ? EXAMPLE_TICKERS : list.map((x) => x.ticker);
    navigate(resolveTickerRoute(ticker, known));
  };

  return (
    <form onSubmit={onSubmit} className="flex gap-2 max-w-md">
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Ticker, e.g. NVDA"
        aria-label="Ticker"
        autoCapitalize="characters"
        autoFocus={autoFocus}
        className="flex-1 min-w-0 rounded-md border border-border bg-secondary px-3 py-2 text-sm uppercase placeholder:normal-case focus:outline-none focus:ring-1 focus:ring-primary"
      />
      <button
        type="submit"
        disabled={isLoading}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        Analyze
      </button>
    </form>
  );
}

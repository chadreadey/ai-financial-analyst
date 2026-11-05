import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BriefView } from "@/components/brief/BriefView";
import { ProgressStream } from "@/components/analysis/ProgressStream";
import { TickerForm } from "@/components/public/TickerForm";
import { useAnalysis } from "@/hooks/useAnalysis";
import { parseApiError } from "@/lib/brief";

export function LiveRunPage() {
  const [params] = useSearchParams();
  const ticker = (params.get("ticker") ?? "").trim().toUpperCase();
  const { isRunning, progress, result, error, run } = useAnalysis();
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (!ticker || started.current === ticker) return;
    started.current = ticker;
    run({ ticker });
  }, [ticker, run]);

  if (!ticker) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">Analyze a ticker</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Six analyst agents run in parallel and a synthesis agent reconciles them into one brief.
          Example tickers open a cached brief instantly; anything else runs live and takes a few
          minutes.
        </p>
        <TickerForm autoFocus />
        <p className="text-xs text-muted-foreground">
          Not sure what to try?{" "}
          <Link to="/" className="text-primary underline-offset-4 hover:underline">
            Browse the example briefs
          </Link>
          .
        </p>
      </div>
    );
  }

  if (error) {
    const { status, detail } = parseApiError(error);
    const busy = status === 429 && /in progress|concurrent/i.test(detail);
    const showExamples = status === 422 || (status === 429 && !busy);
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-bold text-foreground">Could not run {ticker}</h1>
        <p className="text-sm text-muted-foreground break-words">{detail}</p>
        {showExamples ? (
          <Link to="/" className="inline-block text-sm text-primary underline">Browse the example briefs</Link>
        ) : (
          <button
            onClick={() => run({ ticker })}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Try again
          </button>
        )}
      </div>
    );
  }

  if (result) return <BriefView result={result} />;

  return (
    <div className="space-y-3">
      <h1 className="text-xl font-bold text-foreground">Analyzing {ticker}</h1>
      {(isRunning || !result) && <ProgressStream progress={progress ?? { step: "", pct: 0 }} />}
    </div>
  );
}

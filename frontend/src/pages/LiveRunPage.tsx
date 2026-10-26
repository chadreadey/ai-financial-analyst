import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BriefView } from "@/components/brief/BriefView";
import { ProgressStream } from "@/components/analysis/ProgressStream";
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

  if (!ticker) return <p className="text-sm text-muted-foreground">Pick a ticker from the home page.</p>;

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

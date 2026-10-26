import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { BriefView } from "@/components/brief/BriefView";
import { fetchShowcaseBrief } from "@/lib/showcase";
import type { ShowcaseBrief } from "@/lib/showcase";

type Loaded = { ticker: string; attempt: number; brief: ShowcaseBrief | null; failed: boolean };

export function BriefPage() {
  const { ticker = "" } = useParams();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchShowcaseBrief(ticker)
      .then((brief) => ({ brief, failed: false }))
      .catch(() => ({ brief: null, failed: true }))
      .then((r) => {
        if (!cancelled) setLoaded({ ticker, attempt, ...r });
      });
    return () => {
      cancelled = true;
    };
  }, [ticker, attempt]);

  const current = loaded?.ticker === ticker && loaded.attempt === attempt ? loaded : null;

  if (!current) return <p className="text-sm text-muted-foreground">Loading brief...</p>;
  if (current.failed) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">Couldn't load this example. Try again.</p>
        <button
          onClick={() => setAttempt((n) => n + 1)}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!current.brief) {
    const t = ticker.toUpperCase();
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-bold text-foreground">No example for {t}</h1>
        <Link
          to={`/run?ticker=${encodeURIComponent(t)}`}
          className="inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          Run it live
        </Link>
      </div>
    );
  }
  return <BriefView result={current.brief.result} runAt={current.brief.run_at} isExample />;
}

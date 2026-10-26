import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { BriefView } from "@/components/brief/BriefView";
import { fetchShowcaseBrief } from "@/lib/showcase";
import type { ShowcaseBrief } from "@/lib/showcase";

export function BriefPage() {
  const { ticker = "" } = useParams();
  const [loaded, setLoaded] = useState<{ ticker: string; brief: ShowcaseBrief | null } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchShowcaseBrief(ticker)
      .catch(() => null)
      .then((b) => {
        if (!cancelled) setLoaded({ ticker, brief: b });
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const brief = loaded?.ticker === ticker ? loaded.brief : null;
  const state = loaded?.ticker !== ticker ? "loading" : brief ? "ready" : "missing";

  if (state === "loading") return <p className="text-sm text-muted-foreground">Loading brief...</p>;
  if (state === "missing" || !brief) {
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
  return <BriefView result={brief.result} runAt={brief.run_at} isExample />;
}

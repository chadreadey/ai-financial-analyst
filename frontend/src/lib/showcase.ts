import type { AnalysisResult } from "@/api/types";

export interface ShowcaseIndexEntry {
  ticker: string;
  company_name: string;
  verdict: string;
  conviction: number | string | null;
  price_target: number | null;
  entry_price: number | null;
  has_conflicts: boolean;
  run_at: string;
}

export interface ShowcaseBrief {
  run_at: string;
  result: AnalysisResult;
}

/** Fallback so example tickers never route to the paid live-run path. */
export const EXAMPLE_TICKERS = ["NVDA", "JPM", "KO", "XOM"];

// vercel.json rewrites unknown paths to index.html, so a missing file can be 200 HTML.
function isJson(res: Response): boolean {
  return (res.headers.get("content-type") ?? "").includes("application/json");
}

export async function fetchShowcaseIndex(): Promise<ShowcaseIndexEntry[]> {
  const res = await fetch("/showcase/index.json");
  if (!res.ok || !isJson(res)) throw new Error("Example briefs are unavailable");
  const data = await res.json();
  return data.briefs ?? [];
}

export async function fetchShowcaseBrief(ticker: string): Promise<ShowcaseBrief | null> {
  const res = await fetch(`/showcase/${encodeURIComponent(ticker.toUpperCase())}.json`);
  if (!res.ok || !isJson(res)) return null;
  return res.json();
}

export function resolveTickerRoute(input: string, examples: string[]): string {
  const ticker = input.trim().toUpperCase();
  if (examples.includes(ticker)) return `/brief/${ticker}`;
  return `/run?ticker=${encodeURIComponent(ticker)}`;
}

/** SEC titles arrive in all caps; title-case those, leave mixed case alone. */
export function formatCompanyName(name: string): string {
  if (!name || name !== name.toUpperCase()) return name;
  return name.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

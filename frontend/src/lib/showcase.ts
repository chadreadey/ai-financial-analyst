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

export async function fetchShowcaseIndex(): Promise<ShowcaseIndexEntry[]> {
  const res = await fetch("/showcase/index.json");
  if (!res.ok) throw new Error(`Failed to load examples (${res.status})`);
  const data = await res.json();
  return data.briefs ?? [];
}

export async function fetchShowcaseBrief(ticker: string): Promise<ShowcaseBrief | null> {
  const res = await fetch(`/showcase/${encodeURIComponent(ticker.toUpperCase())}.json`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Failed to load brief (${res.status})`);
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

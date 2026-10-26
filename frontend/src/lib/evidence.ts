export const SERIES_NAMES = ["SPY", "Quant-only", "AI-augmented"] as const;
export type SeriesName = (typeof SERIES_NAMES)[number];

export interface SeriesStats {
  sharpe: number;
  sortino: number;
  ann_return_pct: number;
  max_dd_pct: number;
  total_return_pct: number;
  days: number;
}

export interface CurvePoint {
  date: string;
  SPY: number;
  "Quant-only": number;
  "AI-augmented": number;
}

export interface EvidencePayload {
  series: Record<SeriesName, SeriesStats>;
  curve: CurvePoint[];
  attribution: Record<string, Record<string, number>>;
  config: { n_positions: number; max_per_sector: number };
  generated_at: string;
}

// vercel.json rewrites unknown paths to index.html, so a missing file can be 200 HTML.
function isJson(res: Response): boolean {
  return (res.headers.get("content-type") ?? "").includes("application/json");
}

export async function fetchEvidence(): Promise<EvidencePayload> {
  const res = await fetch("/evidence/three_series.json");
  if (!res.ok || !isJson(res)) throw new Error("Performance data is unavailable");
  return res.json();
}

/** a minus b, two decimals, true minus sign (U+2212), explicit plus when positive. */
export function formatDelta(a: number, b: number): string {
  const d = Math.round((a - b) * 100) / 100;
  if (d === 0) return "0.00";
  const text = Math.abs(d).toFixed(2);
  return d > 0 ? `+${text}` : `−${text}`;
}

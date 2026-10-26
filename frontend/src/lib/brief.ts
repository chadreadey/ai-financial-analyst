export type AgentKey = "dcf" | "risk" | "earnings" | "competitive" | "pattern" | "macro";
export type Stance = "bullish" | "neutral" | "bearish";

export interface AgentStance {
  agent: AgentKey;
  label: string;
  score: number;
  weight: number;
  stance: Stance;
}

const AGENTS: { key: AgentKey; label: string }[] = [
  { key: "dcf", label: "DCF" },
  { key: "risk", label: "Risk" },
  { key: "earnings", label: "Earnings" },
  { key: "competitive", label: "Competitive" },
  { key: "pattern", label: "Pattern" },
  { key: "macro", label: "Macro" },
];

export function stanceFor(score: number): Stance {
  if (score >= 0.2) return "bullish";
  if (score <= -0.2) return "bearish";
  return "neutral";
}

export type VerdictData = Record<string, unknown>;

export function buildConsensus(verdict: VerdictData | null): AgentStance[] {
  const sb = verdict?.signal_breakdown as Record<string, { score?: unknown; weight?: unknown } | undefined> | undefined;
  if (!sb || typeof sb !== "object") return [];
  const out: AgentStance[] = [];
  for (const { key, label } of AGENTS) {
    const entry = sb[key];
    if (!entry || typeof entry.score !== "number") continue;
    out.push({
      agent: key,
      label,
      score: entry.score,
      weight: typeof entry.weight === "number" ? entry.weight : 0,
      stance: stanceFor(entry.score),
    });
  }
  return out;
}

const CONFLICT_RE = /^(dcf|risk|earnings|competitive|pattern|macro)_(bullish|neutral|bearish)_vs_(dcf|risk|earnings|competitive|pattern|macro)_(bullish|neutral|bearish)$/;

function labelOf(key: string): string {
  return AGENTS.find((a) => a.key === key)?.label ?? key;
}

export function parseConflict(code: string): string | null {
  const m = CONFLICT_RE.exec(code);
  if (!m) return null;
  return `${labelOf(m[1])} (${m[2]}) vs ${labelOf(m[3])} (${m[4]})`;
}

/** Readable text for any conflict code: parsed form, else underscores to spaces. */
export function describeConflict(code: string): string {
  const parsed = parseConflict(code);
  if (parsed) return parsed;
  const text = code.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function upsidePct(
  entry: number | null | undefined,
  target: number | null | undefined,
): number | null {
  if (entry == null || target == null || entry <= 0) return null;
  return (target / entry - 1) * 100;
}

export function verdictClassName(verdict: string): string {
  const v = verdict.toUpperCase();
  if (v.includes("BUY") || v.includes("BULLISH")) return "bg-[--positive]/10 text-[--positive] border-[--positive]/20";
  if (v.includes("SELL") || v.includes("BEARISH")) return "bg-[--negative]/10 text-[--negative] border-[--negative]/20";
  if (v.includes("HOLD") || v.includes("NEUTRAL")) return "bg-[--warning]/10 text-[--warning] border-[--warning]/20";
  return "bg-primary/10 text-primary border-primary/20";
}

/** Turn client.ts's "API error <status>: <body>" into a user-facing message. */
export function parseApiError(message: string): { status: number | null; detail: string } {
  const m = /^API error (\d+):\s*([\s\S]*)$/.exec(message);
  if (!m) return { status: null, detail: message };
  const status = Number(m[1]);
  const body = m[2].trim();
  try {
    const parsed = JSON.parse(body);
    if (parsed && typeof parsed.detail === "string") return { status, detail: parsed.detail };
  } catch {
    // not JSON; fall through
  }
  return { status, detail: body || message };
}

export function formatRunDate(runAt: string): string {
  const d = new Date(runAt);
  if (isNaN(d.getTime())) return runAt;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

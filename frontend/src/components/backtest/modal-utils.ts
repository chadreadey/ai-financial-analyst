export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "2-digit", month: "short", day: "2-digit" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function formatDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return "—";
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

export function formatNum(v: number | null | undefined, digits: number = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function formatPct(v: number | null | undefined, digits: number = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function shortHash(s: string | null | undefined, chars: number = 8): string {
  if (!s) return "—";
  return s.length <= chars ? s : s.slice(0, chars);
}

/** Color-coded tailwind class for a signed number (profit/loss, sharpe, etc). */
export function signedClass(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "text-muted-foreground";
  if (v > 0) return "text-[--positive]";
  if (v < 0) return "text-[--negative]";
  return "text-muted-foreground";
}

/**
 * Pull `{signal_name -> score}` out of the `signals_at_entry_json` column.
 *
 * The canonical payload is `TradeRecord.to_json_dict`'s snapshot:
 *   `{ flags: string[], actionable: bool, signal_vector: { rsi: {score, detail, ...}, ... } }`
 *
 * Some older combos in the warehouse only stored a flat `{ rsi: 0.34, ... }` map,
 * so we fall back to that shape when `signal_vector` isn't present.
 */
export function extractSignalScores(
  payload: Record<string, any> | null | undefined,
): Array<[string, number]> {
  if (!payload) return [];
  const sv = (payload as any).signal_vector;
  if (sv && typeof sv === "object") {
    return Object.entries(sv)
      .map(([k, v]) => {
        const score = (v as any)?.score;
        return typeof score === "number" ? ([k, score] as [string, number]) : null;
      })
      .filter((x): x is [string, number] => x !== null);
  }
  // Legacy shape: flat map of scores.
  return Object.entries(payload)
    .filter(([, v]) => typeof v === "number")
    .map(([k, v]) => [k, v as number] as [string, number]);
}

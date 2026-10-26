import { describe, expect, it } from "vitest";
import { buildConsensus, parseApiError, parseConflict, upsidePct } from "./brief";

describe("buildConsensus", () => {
  it("returns [] for null or missing breakdown", () => {
    expect(buildConsensus(null)).toEqual([]);
    expect(buildConsensus({})).toEqual([]);
  });
  it("keeps fixed agent order, labels and stance thresholds", () => {
    const out = buildConsensus({
      signal_breakdown: {
        macro: { score: -0.2, weight: 0.12 },
        dcf: { score: 0.2, weight: 0.17 },
        risk: { score: 0.19, weight: 0.17 },
      },
    });
    expect(out.map((a) => a.label)).toEqual(["DCF", "Risk", "Macro"]);
    expect(out.map((a) => a.stance)).toEqual(["bullish", "neutral", "bearish"]);
    expect(out[0]).toMatchObject({ agent: "dcf", score: 0.2, weight: 0.17 });
  });
});

describe("parseConflict", () => {
  it("parses agent/stance pairs", () => {
    expect(parseConflict("risk_bearish_vs_earnings_bullish")).toBe("Risk (bearish) vs Earnings (bullish)");
  });
  it("returns null otherwise", () => {
    expect(parseConflict("garbage")).toBeNull();
    expect(parseConflict("price_momentum_vs_data_integrity_failure")).toBeNull();
  });
});

describe("upsidePct", () => {
  it("computes upside", () => {
    expect(upsidePct(210.35, 242)).toBeCloseTo(15.05, 2);
    expect(upsidePct(183.21, 183.21)).toBe(0);
  });
  it("returns null for missing or bad entry", () => {
    expect(upsidePct(null, 242)).toBeNull();
    expect(upsidePct(100, null)).toBeNull();
    expect(upsidePct(0, 242)).toBeNull();
  });
});

describe("parseApiError", () => {
  it("extracts detail from a JSON body", () => {
    expect(parseApiError('API error 429: {"detail":"Daily limit reached"}')).toEqual({
      status: 429,
      detail: "Daily limit reached",
    });
  });
  it("falls back to the raw body when not JSON", () => {
    expect(parseApiError("API error 500: Internal Server Error")).toEqual({
      status: 500,
      detail: "Internal Server Error",
    });
  });
  it("handles plain messages", () => {
    expect(parseApiError("Failed to fetch")).toEqual({ status: null, detail: "Failed to fetch" });
  });
});

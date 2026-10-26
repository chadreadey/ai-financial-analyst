import { describe, expect, test } from "vitest";
import { formatCompanyName, resolveTickerRoute } from "./showcase";

describe("resolveTickerRoute", () => {
  test("routes a known example to its brief", () => {
    expect(resolveTickerRoute(" nvda ", ["NVDA", "JPM"])).toBe("/brief/NVDA");
  });
  test("routes an unknown ticker to a live run", () => {
    expect(resolveTickerRoute("amd", ["NVDA"])).toBe("/run?ticker=AMD");
  });
  test("keeps dots in tickers", () => {
    expect(resolveTickerRoute("brk.b", [])).toBe("/run?ticker=BRK.B");
  });
});

describe("formatCompanyName", () => {
  test("title-cases all-caps names", () => {
    expect(formatCompanyName("COCA COLA CO")).toBe("Coca Cola Co");
    expect(formatCompanyName("NVIDIA CORP")).toBe("Nvidia Corp");
    expect(formatCompanyName("JPMORGAN CHASE & CO")).toBe("Jpmorgan Chase & Co");
  });
  test("leaves mixed case unchanged", () => {
    expect(formatCompanyName("Exxon Mobil Corporation")).toBe("Exxon Mobil Corporation");
  });
  test("handles empty string", () => {
    expect(formatCompanyName("")).toBe("");
  });
});

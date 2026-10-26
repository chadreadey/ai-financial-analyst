import { afterEach, describe, expect, test, vi } from "vitest";
import {
  fetchShowcaseBrief,
  fetchShowcaseIndex,
  formatCompanyName,
  resolveTickerRoute,
} from "./showcase";

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

function stubFetch(status: number, contentType: string, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status,
        headers: { "content-type": contentType },
      })
    )
  );
}

describe("fetchShowcaseBrief", () => {
  afterEach(() => vi.unstubAllGlobals());
  test("404 returns null", async () => {
    stubFetch(404, "text/plain", "nope");
    expect(await fetchShowcaseBrief("XYZ")).toBeNull();
  });
  test("200 HTML (SPA rewrite) returns null", async () => {
    stubFetch(200, "text/html", "<html></html>");
    expect(await fetchShowcaseBrief("XYZ")).toBeNull();
  });
  test("200 JSON returns the parsed object", async () => {
    const body = { run_at: "2026-01-01", result: { ticker: "NVDA" } };
    stubFetch(200, "application/json", body);
    expect(await fetchShowcaseBrief("NVDA")).toEqual(body);
  });
});

describe("fetchShowcaseIndex", () => {
  afterEach(() => vi.unstubAllGlobals());
  test("HTML response throws a clear error", async () => {
    stubFetch(200, "text/html", "<html></html>");
    await expect(fetchShowcaseIndex()).rejects.toThrow("Example briefs are unavailable");
  });
});

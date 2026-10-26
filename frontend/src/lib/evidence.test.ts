import { afterEach, describe, expect, test, vi } from "vitest";
import { fetchEvidence, formatDelta, yearTicks } from "./evidence";

describe("formatDelta", () => {
  test("uses a true minus sign for a decrease", () => {
    expect(formatDelta(1.01, 1.15)).toBe("−0.14");
  });
  test("prefixes + for an increase", () => {
    expect(formatDelta(1.15, 0.74)).toBe("+0.41");
  });
  test("no sign when equal", () => {
    expect(formatDelta(1, 1)).toBe("0.00");
  });
});

describe("yearTicks", () => {
  test("first date of each year, no duplicates", () => {
    const curve = [
      "2018-02-02", "2018-02-09", "2018-12-28", "2019-01-04", "2019-06-07", "2019-12-27",
    ].map((date) => ({ date }));
    expect(yearTicks(curve)).toEqual(["2018-02-02", "2019-01-04"]);
  });
});

describe("fetchEvidence", () => {
  afterEach(() => vi.unstubAllGlobals());
  const stub = (res: Response) => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(res));

  test("throws on 404", async () => {
    stub(new Response("nope", { status: 404 }));
    await expect(fetchEvidence()).rejects.toThrow();
  });
  test("throws on 200 HTML", async () => {
    stub(new Response("<html/>", { status: 200, headers: { "content-type": "text/html" } }));
    await expect(fetchEvidence()).rejects.toThrow();
  });
  test("returns parsed JSON", async () => {
    stub(
      new Response(JSON.stringify({ generated_at: "x" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    await expect(fetchEvidence()).resolves.toEqual({ generated_at: "x" });
  });
});

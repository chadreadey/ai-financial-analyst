import { describe, expect, test } from "vitest";
import { formatDelta } from "./evidence";

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

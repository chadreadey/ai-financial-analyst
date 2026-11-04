import { describe, expect, it } from "vitest";
import { dropRetiredDefaults } from "./settingsMigration";

describe("dropRetiredDefaults", () => {
  it("drops saved budgets that still equal the retired defaults", () => {
    const out = dropRetiredDefaults({
      provider: "anthropic",
      max_agent_output_tokens: 1200,
      synthesis_input_max_chars: 22000,
      max_synthesis_output_tokens: 1500,
    });
    expect(out).toEqual({ provider: "anthropic" });
  });
  it("keeps budgets the user chose", () => {
    const saved = { max_agent_output_tokens: 2000, max_synthesis_output_tokens: 4000 };
    expect(dropRetiredDefaults(saved)).toEqual(saved);
  });
});

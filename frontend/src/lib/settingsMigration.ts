// Retired defaults: at these budgets agents ran out of tokens before their
// SIGNAL_SCORE line. A saved copy still holding one gets the current default.
const RETIRED_DEFAULTS: Record<string, number> = {
  max_agent_output_tokens: 1200,
  synthesis_input_max_chars: 22000,
  max_synthesis_output_tokens: 1500,
};

export function dropRetiredDefaults<T extends object>(stored: T): Partial<T> {
  const out = { ...stored } as Record<string, unknown>;
  for (const [key, value] of Object.entries(RETIRED_DEFAULTS)) {
    if (out[key] === value) delete out[key];
  }
  return out as Partial<T>;
}

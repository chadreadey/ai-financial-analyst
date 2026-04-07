# LLM Cost Analysis: 6-Agent Equity Research at Scale

## Token Math Per Stock
- Input per agent call: ~12,000 tokens (from config max_agent_context_chars)
- Output per agent call: ~1,200 tokens (max_agent_output_tokens)
- Calls per stock: 7 (DCF + Risk + Earnings + Competitive + Pattern + Macro + Synthesis)
- **Total per stock: 84,000 input + 8,400 output tokens**

## Cost Comparison (Monthly)

| Model | Input $/M | Output $/M | 50 stocks | 200 stocks | Quality |
|---|---|---|---|---|---|
| **Claude Sonnet 4.6** | $3.00 | $15.00 | $18.90 | $75.60 | Best structured output + reasoning |
| Claude Sonnet + batch API | $1.50 | $7.50 | $9.45 | $37.80 | Same quality, 24hr turnaround |
| **DeepSeek V3** | $0.28 | $0.42 | $1.73 | $6.93 | Strong; ~85% MATH benchmark |
| Mistral Large 3 | $0.50 | $1.50 | $2.62 | $10.50 | Good structured extraction |
| Groq (Llama 3.3 70B) | $0.59 | $0.79 | $3.10 | $12.42 | Open weights, ultra-fast |
| GPT-4o-mini | $0.15 | $0.60 | $0.77 | $3.06 | Arithmetic unreliable for DCF |

## Hybrid Architecture (Recommended)

Run specialists on DeepSeek V3, reserve Claude for Synthesis:

| Component | Model | 50 stocks | 200 stocks |
|---|---|---|---|
| 6 specialist agents | DeepSeek V3 | $1.49 | $5.95 |
| 1 synthesis agent | Claude Sonnet | $3.15 | $12.60 |
| **Hybrid total** | | **$4.64** | **$18.55** |
| vs. all-Claude | | $18.90 | $75.60 |
| **Savings** | | **75%** | **75%** |

DeepSeek API is OpenAI-compatible — config.py already has openai_base_url field.

## Quality Notes
- **Structured JSON**: Claude best, DeepSeek V3 very good, GPT-4o-mini truncates at edge of context
- **DCF/ratio math**: Claude and DeepSeek ~equivalent (85-88% MATH benchmark). GPT-4o-mini makes arithmetic errors on multi-step chains.
- **Scoring rubrics**: Claude best at following 10-point rubrics with sub-scores. DeepSeek second.
- **Reproducibility**: All managed APIs deliver deterministic output at temperature=0
- **Self-hosted 70B on Mac M-series**: ~8 tok/sec via llama.cpp — too slow for batch (350 calls × 150s = 14 hours)

## Recommendations
1. **Now (50 stocks)**: Stay on Claude Sonnet with batch API — $9.45/mo
2. **Scale (200 stocks)**: Hybrid DeepSeek + Claude — $18.55/mo
3. **Avoid GPT-4o-mini** for financial agents — arithmetic reliability gap corrupts scoring chain
4. **Columbia CBS AI endpoint** (openai_cbs_api_key in config) — check if this provides free/subsidized access

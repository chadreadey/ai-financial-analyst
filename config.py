"""
Centralized application configuration.

All environment variables are loaded and validated at startup via
Pydantic BaseSettings.  Modules should import ``settings`` rather than
calling ``os.getenv`` directly.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────────────────────
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://cbsai.business.columbia.edu/api/v1"
    openai_cbs_api_key: str = ""
    enable_prompt_caching: bool = True

    # ── SEC / Edgar ────────────────────────────────────────────────
    sec_user_agent: str = "AIFinancialAnalyst admin@example.com"
    edgar_identity: str = ""
    enable_edgartools: bool = True
    enable_filing_text: bool = True

    # ── Feature flags ──────────────────────────────────────────────
    enable_macro_agent: bool = True
    enable_yahoo: bool = True
    enable_tavily: bool = True
    enable_peers: bool = True
    enable_estimates: bool = True
    enable_price_history: bool = True
    enable_macro: bool = True
    enable_fred: bool = True
    enable_rag: bool = False
    enable_wacc_helpers: bool = True
    enable_quantstats: bool = True
    enable_sector_specialists: bool = True
    tavily_raw_content: bool = True

    # ── API keys ───────────────────────────────────────────────────
    tavily_api_key: str = ""
    fred_api_key: str = ""
    openai_embed_key: str = ""

    # ── Agent context budgets ──────────────────────────────────────
    max_agent_context_chars: int = 12000
    max_agent_output_tokens: int = 1200
    max_context_dcf_chars: int = 0
    max_context_risk_chars: int = 0
    max_context_earnings_chars: int = 0
    max_context_competitive_chars: int = 15000
    max_context_pattern_chars: int = 0
    max_context_macro_chars: int = 0

    # ── Synthesis budgets ──────────────────────────────────────────
    synthesis_report_max_chars: int = 4500
    synthesis_input_max_chars: int = 22000
    max_synthesis_output_tokens: int = 1500

    # ── Enrichment section caps ────────────────────────────────────
    max_market_section_chars: int = 1200
    max_estimates_section_chars: int = 1200
    max_external_company_section_chars: int = 2500
    max_external_industry_section_chars: int = 2500
    max_external_risks_section_chars: int = 2500
    max_price_history_chars: int = 1500
    max_macro_section_chars: int = 1500
    max_peer_section_chars: int = 2500
    enrichment_max_chars: int = 8000
    tavily_snippet_chars: int = 600
    tavily_max_results: int = 3
    max_sector_tavily_chars: int = 2000

    # ── Sector specialist ──────────────────────────────────────────
    max_sector_briefing_tokens: int = 600
    max_sector_briefing_chars: int = 2500

    # ── Enrichment concurrency (I/O-bound workers) ───────────────────
    enrichment_max_workers: int = 8
    fred_max_workers: int = 4
    peer_validation_max_workers: int = 5

    # ── Filing section caps ────────────────────────────────────────
    max_mda_chars: int = 4000
    max_risk_factors_chars: int = 3000
    max_biz_desc_chars: int = 2000

    # ── RAG ────────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "financial_research"
    rag_top_k: int = 5
    rag_max_chars: int = 2000

    # ── Logging ────────────────────────────────────────────────────
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def resolved_edgar_identity(self) -> str:
        return self.edgar_identity or self.sec_user_agent


settings = Settings()

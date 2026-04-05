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
    enable_tiingo: bool = True
    enable_fmp: bool = True
    enable_yahoo_fallback: bool = True
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
    tiingo_api_key: str = ""
    fmp_api_key: str = ""
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
    max_fmp_estimates_section_chars: int = 1800
    max_external_company_section_chars: int = 2500
    max_external_industry_section_chars: int = 2500
    max_external_risks_section_chars: int = 2500
    max_price_history_chars: int = 1500
    max_macro_section_chars: int = 1500
    max_peer_section_chars: int = 2500
    enrichment_max_chars: int = 10000
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
    max_market_risk_chars: int = 2000
    max_legal_proceedings_chars: int = 1500
    max_properties_chars: int = 1000
    max_tenq_mda_chars: int = 3000
    max_tenq_risk_update_chars: int = 1500
    max_tenq_market_risk_chars: int = 1500

    # ── RAG ────────────────────────────────────────────────────────
    pinecone_api_key: str = ""
    pinecone_index_name: str = "financial-analyst"
    pinecone_namespace: str = ""
    pinecone_embed_model: str = "text-embedding-3-small"
    pinecone_embed_dimensions: int = 1536
    pinecone_upsert_batch_size: int = 100
    rag_top_k: int = 5
    rag_max_chars: int = 1500

    # ── RAG time-series namespaces ──────────────────────────────────
    pinecone_financial_ts_namespace: str = "financial_ts"
    pinecone_macro_ts_namespace: str = "macro_ts"
    rag_financial_history_top_k: int = 6
    rag_macro_history_top_k: int = 3
    rag_financial_history_max_chars: int = 2000
    rag_macro_history_max_chars: int = 1200
    enable_financial_history_rag: bool = False
    enable_macro_history_rag: bool = False

    # ── Logging ────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Warehouse ───────────────────────────────────────────────────
    enable_warehouse: bool = False
    warehouse_db_path: str = ".warehouse.db"
    warehouse_filing_limit: int = 20
    warehouse_sections_limit: int = 3
    warehouse_tenq_limit: int = 4
    warehouse_market_ttl_hours: int = 4
    warehouse_macro_ttl_hours: int = 24
    warehouse_check_interval_hours: int = 6

    # ── Supabase history sync ────────────────────────────────────────
    enable_supabase_history: bool = False
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_history_table: str = "analyses"

    # ── Auto paper trading ────────────────────────────────────────────
    auto_paper_trade: bool = True
    auto_paper_trade_min_conviction: float = 0.40

    # ── TimesFM ──────────────────────────────────────────────────────
    enable_timesfm: bool = False
    redis_url: str = ""
    timesfm_checkpoint_dir: str = ""
    timesfm_batch_tickers: str = ""
    timesfm_horizon_days: int = 10
    timesfm_price_lookback_days: int = 512
    timesfm_ttl_seconds: int = 86400

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def resolved_edgar_identity(self) -> str:
        return self.edgar_identity or self.sec_user_agent


settings = Settings()

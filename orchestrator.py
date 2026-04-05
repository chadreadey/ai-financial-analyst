"""
Orchestrator: Phase 1 fan-out + Phase 2 synthesis.

Phase 1: Run all analyst agents (5 core + optional Macro) in parallel via asyncio.gather().
Phase 2: Feed all agent outputs to a synthesis agent that
         cross-references findings and produces the final brief.
"""

import asyncio
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents import (
    DCFAgent,
    RiskAgent,
    EarningsAgent,
    CompetitiveAgent,
    PatternAgent,
    MacroAgent,
    SectorSpecialistAgent,
)
from config import settings
from context_budget import trim_text
from llm import LLMProvider, get_provider
from market_enrichment import build_enrichment_context
from models import AgentReport, AnalysisData, AnalysisResult, FilingInfo
from prompt_loader import load_prompt_file, render_prompt
from sec.client import SECClient
from sec.filing_parser import parse_filing_sections
from sec.xbrl_parser import XBRLParser

logger = logging.getLogger(__name__)


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").strip())
        except ValueError:
            return None
    return None


def _extract_structured_block(synthesis_text: str) -> Tuple[Optional[dict], str]:
    """
    Extract the structured JSON block from the end of synthesis output.
    Returns (parsed_dict_or_None, prose_text_with_json_removed).
    """
    patterns = [
        r"```json\s*\n(\{.*?\})\s*\n```",
        r"```\s*\n(\{.*?\})\s*\n```",
    ]
    match = None
    for pattern in patterns:
        match = re.search(pattern, synthesis_text, re.DOTALL)
        if match:
            break
    if not match:
        return None, synthesis_text

    raw_json = match.group(1).strip()
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, ValueError):
        # Parser tolerance: common LLM issue is trailing commas.
        sanitized = re.sub(r",\s*([}\]])", r"\1", raw_json)
        try:
            data = json.loads(sanitized)
        except (json.JSONDecodeError, ValueError):
            return None, synthesis_text

    if not isinstance(data, dict):
        return None, synthesis_text

    before = synthesis_text[:match.start()].strip()
    after = synthesis_text[match.end():].strip()
    prose = f"{before}\n\n{after}".strip() if before and after else (before or after)
    return data, prose


SYNTHESIS_PROMPT_FILE = Path("prompts/synthesis.md")

SECTOR_SPECIALIST_MAP: dict[str, str] = {
    "Healthcare": "prompts/sector_healthcare.md",
    "Technology": "prompts/sector_technology.md",
    "Energy": "prompts/sector_energy.md",
    "Financial Services": "prompts/sector_financials.md",
    "Financials": "prompts/sector_financials.md",
    "Consumer Cyclical": "prompts/sector_consumer.md",
    "Consumer Defensive": "prompts/sector_consumer.md",
}


def _flywheel_ingest(ticker: str) -> None:
    """
    Background flywheel: bootstrap the warehouse and seed Pinecone for a ticker.

    Runs in a daemon thread after every analysis so that previously-unseen
    tickers are available for RAG on the next query. Safe to re-run —
    all warehouse upserts and Pinecone upsert_records are idempotent.

    Creates its own SECClient and DB connection — never shares state with
    the main thread.
    """
    try:
        from pinecone import Pinecone

        from sec.client import SECClient as _SECClient
        from warehouse.bootstrap import bootstrap_ticker
        from warehouse.change_detector import needs_update, incremental_update
        from warehouse.db import WarehouseDB
        from warehouse.embedder import embed_and_upsert_all

        api_key = settings.pinecone_api_key.strip()
        if not api_key:
            logger.debug("Flywheel: no Pinecone API key, skipping")
            return

        db = WarehouseDB()
        company = db.get_company(ticker)
        sec = _SECClient()

        if company is None:
            logger.info("Flywheel: new ticker %s — bootstrapping warehouse...", ticker)
            bootstrap_ticker(ticker, db, sec)
        elif needs_update(ticker, db, sec):
            logger.info("Flywheel: stale ticker %s — incremental update...", ticker)
            incremental_update(ticker, db, sec)
        else:
            logger.debug("Flywheel: %s is current, skipping", ticker)
            return

        pc = Pinecone(api_key=api_key)
        index = pc.Index(settings.pinecone_index_name)
        summary = embed_and_upsert_all(
            db_path=settings.warehouse_db_path,
            index=index,
            namespace=settings.pinecone_namespace or "__default__",
            tickers=[ticker],
        )
        seeded = sum(summary.values())
        logger.info("Flywheel: %s — %d records seeded to Pinecone", ticker, seeded)

    except Exception:
        logger.warning("Flywheel ingestion failed for %s", ticker, exc_info=True)


def _auto_paper_trade(ticker: str, structured: dict) -> None:
    """
    Auto-enter a paper trading position when conviction meets threshold.
    BUY/STRONG BUY → LONG. SELL/STRONG SELL → SHORT. HOLD → no action.
    """
    import sqlite3 as _sqlite3

    conviction_score = _as_float(structured.get("conviction_score")) or 0.0

    # Fallback: derive from old-style scores (1-10 → 0-1) or conviction string
    if conviction_score == 0.0:
        cs = _as_float(structured.get("composite_score"))
        if not cs:
            health = structured.get("health_scores") or {}
            cs = _as_float(health.get("overall"))
        if cs and cs > 1:
            conviction_score = cs / 10.0
    if conviction_score == 0.0:
        conv_str = (structured.get("conviction") or "").upper()
        if conv_str == "HIGH":
            conviction_score = 0.80
        elif conv_str == "MEDIUM":
            conviction_score = 0.55
        elif conv_str == "LOW":
            conviction_score = 0.30

    logger.info("Auto-paper-trade: %s conviction=%.2f (threshold=%.2f) verdict=%s",
                ticker, conviction_score, settings.auto_paper_trade_min_conviction,
                structured.get("verdict", "?"))

    if conviction_score < settings.auto_paper_trade_min_conviction:
        logger.info("Auto-paper-trade: conviction below threshold for %s, skipping", ticker)
        return

    verdict = (structured.get("verdict") or "").upper()
    if "BUY" in verdict:
        direction = "LONG"
    elif "SELL" in verdict:
        direction = "SHORT"
    else:
        logger.debug("Auto-paper-trade: HOLD verdict for %s, skipping", ticker)
        return

    entry_price = _as_float(structured.get("entry_price")) or 0.0
    if entry_price <= 0:
        logger.warning("Auto-paper-trade: no entry_price for %s, skipping", ticker)
        return

    stop_loss = structured.get("stop_loss", {})
    stop_value = ""
    if isinstance(stop_loss, dict) and stop_loss.get("value"):
        stop_value = f"stop_loss=${stop_loss['value']}"
    elif isinstance(stop_loss, (int, float)):
        stop_value = f"stop_loss=${stop_loss}"

    horizon = structured.get("primary_horizon_days") or structured.get("horizon_days") or ""
    exit_conditions = f"{stop_value}; horizon={horizon}d; sizing={structured.get('sizing_guidance', '')}"

    try:
        conn = _sqlite3.connect(settings.warehouse_db_path)
        # Ensure tables exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                ticker TEXT PRIMARY KEY, entry_price REAL, entry_date TEXT,
                current_price REAL, verdict TEXT DEFAULT '', exit_conditions TEXT DEFAULT '',
                direction TEXT DEFAULT 'LONG', conviction_score REAL
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO paper_positions "
            "(ticker, entry_price, entry_date, verdict, exit_conditions, direction, conviction_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ticker.upper(),
                entry_price,
                __import__("time").strftime("%Y-%m-%d"),
                verdict,
                exit_conditions,
                direction,
                conviction_score,
            ),
        )
        conn.commit()
        conn.close()
        logger.info("Auto-paper-trade: %s %s @ $%.2f (conviction=%.2f)",
                     direction, ticker, entry_price, conviction_score)
    except Exception as exc:
        logger.warning("Auto-paper-trade failed for %s: %s", ticker, exc)


class Orchestrator:
    """
    Coordinates the two-phase analysis pipeline.

    Usage:
        orchestrator = Orchestrator()
        result = asyncio.run(orchestrator.run("AAPL"))
    """

    def __init__(
        self,
        sec_client: Optional[SECClient] = None,
        provider: Optional[LLMProvider] = None,
        llm_provider_name: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.sec_client = sec_client or SECClient()
        self.provider = provider or get_provider(llm_provider_name)
        self.synthesis_model = model or self.provider.default_model
        self.agents = [
            DCFAgent(provider=self.provider, model=self.synthesis_model),
            RiskAgent(provider=self.provider, model=self.synthesis_model),
            EarningsAgent(provider=self.provider, model=self.synthesis_model),
            CompetitiveAgent(provider=self.provider, model=self.synthesis_model),
            PatternAgent(provider=self.provider, model=self.synthesis_model),
        ]
        if settings.enable_macro_agent:
            self.agents.append(
                MacroAgent(provider=self.provider, model=self.synthesis_model)
            )

    def prepare_data(
        self,
        ticker: str,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> AnalysisData:
        """
        Fetch and parse all SEC data for a ticker.
        Returns the unified AnalysisData that agents consume.
        """
        def emit(message: str, pct: Optional[int] = None) -> None:
            if progress_callback:
                try:
                    progress_callback(message, pct)
                except Exception:
                    pass

        emit(f"Preparing data for {ticker.upper()}...", 4)
        if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
            try:
                from warehouse.db import WarehouseDB
                from warehouse.bootstrap import bootstrap_ticker
                from warehouse.change_detector import needs_update, incremental_update
                from warehouse.reader import build_analysis_data_from_warehouse

                emit("Checking warehouse cache...", 7)
                db = WarehouseDB()
                company = db.get_company(ticker.upper())
                if company is None:
                    emit("Bootstrapping warehouse data...", 10)
                    logger.info("Warehouse: bootstrapping %s...", ticker.upper())
                    bootstrap_ticker(ticker.upper(), db, self.sec_client)
                elif needs_update(ticker.upper(), db, self.sec_client):
                    emit("Refreshing stale warehouse data...", 12)
                    logger.info("Warehouse: updating %s...", ticker.upper())
                    incremental_update(ticker.upper(), db, self.sec_client)

                data = build_analysis_data_from_warehouse(ticker.upper(), db)
                if data is not None:
                    emit("Warehouse data loaded. Enriching context...", 15)
                    logger.info("Warehouse: loaded %s from warehouse", ticker.upper())
                    info = self.sec_client.resolve_ticker(ticker)
                    with ThreadPoolExecutor(max_workers=1) as overlap_pool:
                        enrich_future = overlap_pool.submit(
                            build_enrichment_context, ticker.upper(), info["name"]
                        )
                    enrichment = enrich_future.result()

                    live_sections = dict(enrichment.get("sections", {}))
                    data.enrichment_sections = {**data.enrichment_sections, **live_sections}
                    data.financial_summary = (
                        f"{data.financial_core_summary}\n\n{enrichment.get('text', '')}".strip()
                        if enrichment.get("text")
                        else data.financial_core_summary
                    )
                    data.enrichment_warnings = enrichment.get("warnings", [])
                    data.enrichment_sources = enrichment.get("sources", [])
                    data.enrichment_filter_stats = enrichment.get("filter_stats", {})

                    raw_sector = enrichment.get("sector", "")
                    if raw_sector and raw_sector.lower() not in ("n/a", "none"):
                        data.sector = raw_sector
                    raw_industry = enrichment.get("industry", "")
                    if raw_industry and raw_industry.lower() not in ("n/a", "none"):
                        data.industry = raw_industry

                    emit("Data preparation complete", 22)
                    return data
            except Exception as exc:
                logger.warning("Warehouse read failed, falling back to live: %s", exc)

        emit("Resolving ticker identity and fetching SEC filings...", 8)
        logger.info("Fetching SEC data for %s...", ticker.upper())
        info = self.sec_client.resolve_ticker(ticker)
        ticker_upper = ticker.upper()
        # Overlap enrichment (Yahoo/Tavily/peers/etc.) with SEC filings + facts.
        with ThreadPoolExecutor(max_workers=1) as overlap_pool:
            enrich_future = overlap_pool.submit(
                build_enrichment_context, ticker_upper, info["name"]
            )
            filings, company_facts = self.sec_client.fetch_filings_and_facts(ticker)
        enrichment = enrich_future.result()

        raw = {
            "ticker": ticker_upper,
            "company_name": info["name"],
            "cik": info["cik"],
            "recent_filings": filings,
            "company_facts": company_facts,
        }

        emit("Parsing XBRL fundamentals and key metrics...", 14)
        logger.info("Parsing XBRL financial data...")
        parser = XBRLParser(raw["company_facts"])
        metrics = parser.compute_metrics()

        if settings.enable_edgartools:
            try:
                metrics = parser.supplement_with_edgartools(raw["ticker"], metrics)
                logger.info("Supplemented metrics via edgartools")
            except (ImportError, AttributeError, ValueError, RuntimeError) as exc:
                logger.warning("edgartools supplement skipped: %s", exc)

        emit("Building trend metrics and financial summaries...", 18)
        financial_summary = parser.to_summary_text(metrics=metrics)

        quarterly_metrics = parser.compute_quarterly_metrics(quarters=8)
        quarterly_summary = parser.get_quarterly_summary_text(quarterly_metrics)
        margin_trends = parser.get_historical_margins(years=8)
        cash_flow_trends = parser.get_historical_cash_flow(years=8)

        filing_sections: dict = {"mda": "", "risk_factors": "", "business_description": ""}
        if settings.enable_filing_text:
            try:
                tenk_filings = [
                    f for f in raw["recent_filings"]
                    if f.get("form") == "10-K" and f.get("primaryDocument")
                ]
                if tenk_filings:
                    emit("Extracting filing narratives (10-K sections)...", 20)
                    latest_10k = tenk_filings[0]
                    logger.info("Fetching 10-K filing text for narrative extraction...")
                    html = self.sec_client.get_filing_text(
                        raw["ticker"],
                        latest_10k["accessionNumber"],
                        latest_10k["primaryDocument"],
                    )
                    filing_sections = parse_filing_sections(html, ticker=raw["ticker"])
                    section_count = sum(1 for v in filing_sections.values() if v)
                    logger.info("Extracted %d/3 filing sections", section_count)
            except Exception as exc:
                logger.warning("Filing text extraction failed: %s", exc)

        enrichment_sections = dict(enrichment.get("sections", {}))
        if filing_sections.get("mda"):
            enrichment_sections["filing_mda"] = f"=== 10-K MD&A ===\n{filing_sections['mda']}"
        if filing_sections.get("risk_factors"):
            enrichment_sections["filing_risk_factors"] = f"=== 10-K Risk Factors ===\n{filing_sections['risk_factors']}"
        if filing_sections.get("business_description"):
            enrichment_sections["filing_business"] = f"=== 10-K Business Description ===\n{filing_sections['business_description']}"

        segment_data = metrics.pop("_segment_data", None)  # always pop, even if edgartools was skipped
        if segment_data:
            enrichment_sections["segment_data"] = f"=== Revenue Segments ===\n{segment_data}"

        if settings.enable_timesfm:
            try:
                emit("Loading TimesFM cached signals...", 22)
                from quant.timesfm.cache import get_signals
                from quant.timesfm.enrichment import format_price_signals, format_eps_signals
                tfm_signals = get_signals(ticker_upper)
                if tfm_signals:
                    price_sig = tfm_signals.get("price_forecast")
                    eps_sig = tfm_signals.get("eps_forecast")
                    if price_sig:
                        enrichment_sections["timesfm_price"] = format_price_signals(ticker_upper, price_sig)
                    if eps_sig:
                        enrichment_sections["timesfm_eps"] = format_eps_signals(ticker_upper, eps_sig)
            except Exception as exc:
                logger.warning("TimesFM enrichment injection failed: %s", exc)

        recent_filings = [
            FilingInfo(**{k: f[k] for k in FilingInfo.model_fields if k in f})
            for f in raw["recent_filings"]
        ]

        raw_sector = enrichment.get("sector", "")
        if not raw_sector or raw_sector.lower() in ("n/a", "none"):
            raw_sector = ""
        raw_industry = enrichment.get("industry", "")
        if not raw_industry or raw_industry.lower() in ("n/a", "none"):
            raw_industry = ""

        emit("Data preparation complete", 25)
        return AnalysisData(
            ticker=raw["ticker"],
            company_name=raw["company_name"],
            sector=raw_sector,
            industry=raw_industry,
            financial_core_summary=financial_summary,
            financial_summary=(
                f"{financial_summary}\n\n{enrichment.get('text', '')}".strip()
                if enrichment.get("text")
                else financial_summary
            ),
            metrics=metrics,
            recent_filings=recent_filings,
            historical_revenue=parser.get_historical_revenue(years=8),
            historical_net_income=parser.get_historical_net_income(years=8),
            margin_trends=margin_trends,
            cash_flow_trends=cash_flow_trends,
            quarterly_metrics=quarterly_metrics,
            quarterly_summary=quarterly_summary,
            enrichment_sections=enrichment_sections,
            enrichment_warnings=enrichment.get("warnings", []),
            enrichment_sources=enrichment.get("sources", []),
            enrichment_filter_stats=enrichment.get("filter_stats", {}),
        )

    def _get_sector_specialist(self, data: AnalysisData) -> Optional[SectorSpecialistAgent]:
        prompt_path = SECTOR_SPECIALIST_MAP.get(data.sector)
        if not prompt_path or not Path(prompt_path).exists():
            return None
        return SectorSpecialistAgent(
            prompt_file=prompt_path,
            provider=self.provider,
            model=self.synthesis_model,
        )

    async def _run_agent(
        self,
        agent,
        data: AnalysisData,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> AgentReport:
        if progress_callback:
            progress_callback(f"Agent started: {agent.name}", None)
        logger.info("  %s analyzing...", agent.name)
        result = await agent.analyze(data)
        logger.info("  %s complete", agent.name)
        if progress_callback:
            progress_callback(f"Agent complete: {agent.name}", None)
        return AgentReport(agent_name=agent.name, analysis=result)

    async def run_phase1(
        self,
        data: AnalysisData,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> List[AgentReport]:
        """
        Phase 1: Run all agents in parallel.
        Returns list of AgentReport instances.
        """
        logger.info("Phase 1: Running analyst agents in parallel")
        if progress_callback:
            progress_callback(f"Launching {len(self.agents)} analyst agents in parallel...", 30)
        results = await asyncio.gather(
            *[
                self._run_agent(agent, data, progress_callback=progress_callback)
                for agent in self.agents
            ]
        )
        if progress_callback:
            progress_callback("All primary agents completed", 68)
        return list(results)

    async def run_phase2(
        self,
        ticker: str,
        company_name: str,
        agent_reports: List[AgentReport],
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> str:
        """
        Phase 2: Synthesis agent cross-references all reports.
        Returns the final synthesized analysis.
        """
        logger.info("Phase 2: Synthesis & cross-referencing")
        if progress_callback:
            progress_callback("Preparing synthesis context from agent reports...", 74)

        report_sections = []
        per_report_cap = settings.synthesis_report_max_chars
        for report in agent_reports:
            trimmed_analysis = trim_text(
                report.analysis,
                per_report_cap,
                marker="\n...[agent report trimmed]...",
            )
            report_sections.append(
                f"{'=' * 60}\n"
                f"REPORT FROM: {report.agent_name}\n"
                f"{'=' * 60}\n\n"
                f"{trimmed_analysis}\n"
            )

        combined_reports = "\n\n".join(report_sections)
        combined_reports = trim_text(
            combined_reports,
            settings.synthesis_input_max_chars,
            marker="\n...[synthesis input trimmed]...",
        )
        synthesis_template = load_prompt_file(str(SYNTHESIS_PROMPT_FILE))
        synthesis_system_prompt = render_prompt(
            synthesis_template,
            {"company_name": company_name, "ticker": ticker},
        )

        agent_count = len(agent_reports)
        if progress_callback:
            progress_callback(f"Synthesizing final brief from {agent_count} agent reports...", 82)
        synthesis_text = await self.provider.generate(
            system=synthesis_system_prompt,
            user=(
                f"Company: {company_name} ({ticker})\n\n"
                f"Below are the {agent_count} analyst reports. "
                "Synthesize them into a unified investment brief.\n\n"
                f"{combined_reports}"
            ),
            model=self.synthesis_model,
            max_tokens=settings.max_synthesis_output_tokens,
        )

        logger.info("Synthesis complete")
        if progress_callback:
            progress_callback("Synthesis completed", 90)
        return synthesis_text

    async def run(
        self,
        ticker: str,
        progress_callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> AnalysisResult:
        """
        Execute the full two-phase analysis pipeline for a ticker.

        When a sector specialist is available, uses a split-gather pattern:
          Wave 1: specialist + all non-competitive agents in parallel
          Inject specialist briefing into enrichment_sections
          Wave 2: CompetitiveAgent (sees the briefing)
        Otherwise falls back to the single-gather run_phase1.
        """
        if progress_callback:
            progress_callback(f"Starting analysis for {ticker.upper()}...", 3)
            progress_callback("Fetching SEC/XBRL data and enrichment...", 6)
        data = await asyncio.to_thread(self.prepare_data, ticker, progress_callback)

        specialist = (
            self._get_sector_specialist(data)
            if settings.enable_sector_specialists
            else None
        )

        if specialist:
            non_competitive = [a for a in self.agents if not isinstance(a, CompetitiveAgent)]
            competitive_agents = [a for a in self.agents if isinstance(a, CompetitiveAgent)]

            logger.info("Phase 1 wave 1: Sector specialist + %d agents", len(non_competitive))
            if progress_callback:
                progress_callback(
                    f"Wave 1: running sector specialist + {len(non_competitive)} agents...",
                    32,
                )
            specialist_coro = specialist.analyze(data)
            wave1_coros = [
                self._run_agent(a, data, progress_callback=progress_callback)
                for a in non_competitive
            ]
            specialist_result, *wave1_reports = await asyncio.gather(
                specialist_coro, *wave1_coros
            )
            if progress_callback:
                progress_callback("Sector specialist completed. Updating competitive context...", 58)

            data.enrichment_sections = {
                **data.enrichment_sections,
                "sector_briefing": trim_text(
                    specialist_result, settings.max_sector_briefing_chars
                ),
            }

            logger.info("Phase 1 wave 2: Competitive agent (with sector briefing)")
            if progress_callback:
                progress_callback("Wave 2: running competitive analysis with sector briefing...", 62)
            wave2_reports = [
                await self._run_agent(a, data, progress_callback=progress_callback)
                for a in competitive_agents
            ]
            agent_reports = list(wave1_reports) + list(wave2_reports)
            if progress_callback:
                progress_callback("All analyst waves completed", 68)
        else:
            agent_reports = await self.run_phase1(data, progress_callback=progress_callback)

        raw_synthesis = await self.run_phase2(
            data.ticker,
            data.company_name,
            agent_reports,
            progress_callback=progress_callback,
        )

        structured, synthesis = _extract_structured_block(raw_synthesis)

        if structured:
            try:
                if progress_callback:
                    progress_callback("Saving analysis history and metadata...", 94)
                health = structured.get("health_scores", {})
                stop_loss_value = None
                stop_loss_unit = ""
                raw_stop_loss = structured.get("stop_loss")
                if isinstance(raw_stop_loss, dict):
                    stop_loss_value = _as_float(raw_stop_loss.get("value"))
                    stop_loss_unit = str(raw_stop_loss.get("unit") or "")
                elif isinstance(raw_stop_loss, (int, float)):
                    stop_loss_value = _as_float(raw_stop_loss)
                    stop_loss_unit = "price"

                conviction_score = _as_float(structured.get("conviction_score"))
                weighted_score = _as_float(structured.get("weighted_score"))
                bull_prob = _as_float(structured.get("prior_bull_probability"))
                bear_prob = _as_float(structured.get("prior_bear_probability"))
                sizing = str(structured.get("sizing_guidance") or "")

                self.sec_client.cache.save_analysis(
                    ticker=data.ticker,
                    company_name=data.company_name,
                    verdict=structured.get("verdict", ""),
                    conviction=structured.get("conviction", ""),
                    time_horizon=structured.get("time_horizon", ""),
                    composite_score=health.get("overall"),
                    health_scores=health,
                    price_target=_as_float(structured.get("price_target")),
                    stop_loss_value=stop_loss_value,
                    stop_loss_unit=stop_loss_unit,
                    entry_price_at_run=_as_float(structured.get("entry_price")),
                    conviction_score=conviction_score,
                    bull_probability=bull_prob,
                    bear_probability=bear_prob,
                    weighted_score=weighted_score,
                    sizing_guidance=sizing,
                    result_json={
                        "ticker": data.ticker,
                        "company_name": data.company_name,
                        "agent_reports": [r.model_dump() for r in agent_reports],
                        "synthesis": synthesis,
                        "structured_verdict": structured,
                        "metrics": data.metrics,
                        "enrichment_warnings": data.enrichment_warnings,
                        "enrichment_sources": data.enrichment_sources,
                        "enrichment_filter_stats": data.enrichment_filter_stats,
                    },
                )
                logger.info("Analysis saved to history")
                if progress_callback:
                    progress_callback("History save complete", 97)

                # Auto-paper-trade: enter position if conviction meets threshold
                if settings.auto_paper_trade:
                    _auto_paper_trade(data.ticker, structured)

            except Exception as exc:
                logger.warning("Failed to save analysis history: %s", exc)

        if settings.enable_rag:
            threading.Thread(
                target=_flywheel_ingest,
                args=(data.ticker,),
                daemon=True,
                name=f"flywheel-{data.ticker}",
            ).start()
            if progress_callback:
                progress_callback("Queued background RAG refresh", 98)

        if progress_callback:
            progress_callback("Finalizing report output...", 99)
        return AnalysisResult(
            ticker=data.ticker,
            company_name=data.company_name,
            agent_reports=agent_reports,
            synthesis=synthesis,
            structured_verdict=structured,
            metrics=data.metrics,
            enrichment_warnings=data.enrichment_warnings,
            enrichment_sources=data.enrichment_sources,
            enrichment_filter_stats=data.enrichment_filter_stats,
        )

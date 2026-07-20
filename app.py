import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
import streamlit as st  # type: ignore[import-not-found]
from dotenv import load_dotenv  # type: ignore[import-not-found]

load_dotenv()

from config import settings
from models import AnalysisResult, AgentReport
from orchestrator import Orchestrator
from report import (
    build_pdf_report,
    clean_generated_text,
    list_cached_reports,
    save_pdf_report,
    save_report,
    streamlit_markdown_text,
)
from sec.cache import SECCache
from sec.client import SECClient

logger = logging.getLogger(__name__)


def _set_runtime_env(
    provider: str,
    enable_yahoo: bool,
    enable_tavily: bool,
    enable_tiingo: bool,
    enable_fmp: bool,
    max_agent_context_chars: int,
    max_agent_output_tokens: int,
    synthesis_report_max_chars: int,
    synthesis_input_max_chars: int,
    max_synthesis_output_tokens: int,
) -> None:
    os.environ["LLM_PROVIDER"] = provider
    if provider == "openai":
        cbs_key = os.getenv("OPENAI_CBS_API_KEY") or os.getenv("OPENAI_API_KEY")
        if cbs_key:
            os.environ["OPENAI_API_KEY"] = cbs_key
    os.environ["ENABLE_YAHOO"] = "true" if enable_yahoo else "false"
    os.environ["ENABLE_TAVILY"] = "true" if enable_tavily else "false"
    os.environ["ENABLE_TIINGO"] = "true" if enable_tiingo else "false"
    os.environ["ENABLE_FMP"] = "true" if enable_fmp else "false"
    os.environ["ENABLE_YAHOO_FALLBACK"] = "true" if enable_yahoo else "false"
    os.environ["MAX_AGENT_CONTEXT_CHARS"] = str(max_agent_context_chars)
    os.environ["MAX_AGENT_OUTPUT_TOKENS"] = str(max_agent_output_tokens)
    os.environ["SYNTHESIS_REPORT_MAX_CHARS"] = str(synthesis_report_max_chars)
    os.environ["SYNTHESIS_INPUT_MAX_CHARS"] = str(synthesis_input_max_chars)
    os.environ["MAX_SYNTHESIS_OUTPUT_TOKENS"] = str(max_synthesis_output_tokens)


def _bootstrap_env_from_streamlit_secrets() -> None:
    """
    Copy selected Streamlit secrets into environment variables if missing.
    Useful for Streamlit Community Cloud deployments.
    """
    try:
        secret_keys = [
            "OPENAI_API_KEY",
            "OPENAI_CBS_API_KEY",
            "OPENAI_BASE_URL",
            "TAVILY_API_KEY",
            "FRED_API_KEY",
            "TIINGO_API_KEY",
            "FMP_API_KEY",
            "EDGAR_IDENTITY",
            "SENTRY_DSN",
        ]
        for key in secret_keys:
            if not os.getenv(key) and key in st.secrets:
                val = str(st.secrets[key]).strip()
                if val:
                    os.environ[key] = val
        if os.getenv("OPENAI_CBS_API_KEY"):
            os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_CBS_API_KEY", "")
    except Exception:
        pass


def _init_sentry() -> None:
    """Initialize Sentry error tracking if SENTRY_DSN is configured."""
    if sentry_sdk is None:
        return
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=0.2,
        send_default_pii=False,
    )


def _with_ephemeral_env(env_overrides: dict[str, str], fn):
    """
    Run fn() with temporary env vars, then restore previous env state.
    """
    previous: dict[str, str | None] = {}
    for key, value in env_overrides.items():
        previous[key] = os.getenv(key)
        os.environ[key] = value
    try:
        return fn()
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _run_analysis_sync(
    ticker: str, user_agent: str, provider: str, model: str, progress
) -> AnalysisResult:
    if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
        try:
            from warehouse.db import WarehouseDB
            from warehouse.bootstrap import bootstrap_ticker

            db = WarehouseDB()
            if db.get_company(ticker.upper()) is None:
                progress.write(
                    f"First time analyzing {ticker.upper()} — bootstrapping warehouse (~10s)..."
                )
                bootstrap_ticker(ticker.upper(), db, SECClient(user_agent=user_agent))
                progress.write("Bootstrap complete. Running analysis...")
        except Exception as exc:
            logger.warning("Warehouse bootstrap failed: %s", exc)

    cache = SECCache()
    sec_client = SECClient(user_agent=user_agent, cache=cache)
    orchestrator = Orchestrator(
        sec_client=sec_client,
        llm_provider_name=provider,
        model=(model.strip() or None),
    )

    async def _pipeline() -> AnalysisResult:
        progress.write("Fetching SEC/XBRL data and enrichment...")
        data = orchestrator.prepare_data(ticker)
        progress.write("Running analyst agents in parallel...")
        agent_reports = await orchestrator.run_phase1(data)
        progress.write("Synthesizing final investment brief...")
        raw_synthesis = await orchestrator.run_phase2(data.ticker, data.company_name, agent_reports)
        from orchestrator import _extract_structured_block

        structured, synthesis = _extract_structured_block(raw_synthesis)
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

    try:
        try:
            result = asyncio.run(_pipeline())
        except RuntimeError as re_err:
            if "cannot be called from a running event loop" not in str(re_err):
                raise
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_pipeline())
            finally:
                loop.close()
    finally:
        cache.close()
    return result


def _render_history_sidebar(ticker: str) -> None:
    """Show analysis history for the current ticker in the sidebar."""
    try:
        cache = SECCache()
        history = cache.get_analysis_history(ticker, limit=10)
        cache.close()
    except Exception:
        return

    if not history:
        return

    st.sidebar.markdown("---")
    st.sidebar.subheader(f"Analysis History: {ticker}")

    for entry in history:
        run_date = datetime.fromtimestamp(entry["run_at"]).strftime("%Y-%m-%d %H:%M")
        verdict = entry.get("verdict", "?")
        score = entry.get("composite_score")
        conviction = entry.get("conviction", "")

        score_str = f" | Score: {score:.0f}/10" if score is not None else ""
        conv_str = f" ({conviction})" if conviction else ""
        st.sidebar.text(f"{run_date}: {verdict}{conv_str}{score_str}")

    scores = [
        (e["run_at"], e["composite_score"])
        for e in reversed(history)
        if e.get("composite_score") is not None
    ]
    if len(scores) >= 2:
        import pandas as pd

        df = pd.DataFrame(scores, columns=["date", "score"])
        df["date"] = pd.to_datetime(df["date"], unit="s")
        st.sidebar.line_chart(df.set_index("date")["score"], height=120)


def _render_result(
    result: AnalysisResult, txt_path: str | None = None, pdf_path: str | None = None
) -> None:
    st.subheader(f"{result.company_name} ({result.ticker})")

    sv = result.structured_verdict
    if sv:
        verdict = sv.get("verdict", "")
        conviction = sv.get("conviction", "")
        score = sv.get("health_scores", {}).get("overall")
        badge_parts = [verdict]
        if conviction:
            badge_parts.append(f"Conviction: {conviction}")
        if score is not None:
            badge_parts.append(f"Score: {score}/10")
        st.info(" | ".join(badge_parts))

    st.markdown(streamlit_markdown_text(result.synthesis))

    result_dict = result.model_dump()
    result_dict["agent_reports"] = [(r.agent_name, r.analysis) for r in result.agent_reports]
    pdf_bytes = build_pdf_report(result_dict)

    st.download_button(
        "Download Report (.pdf)",
        data=pdf_bytes,
        file_name=f"{result.ticker}_analysis.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    if txt_path or pdf_path:
        parts = []
        if pdf_path:
            parts.append(f"PDF saved: `{pdf_path}`")
        st.caption(" | ".join(parts))

    _render_history_sidebar(result.ticker)

    tab_names = [r.agent_name for r in result.agent_reports] + ["Enrichment & Diagnostics"]
    tabs = st.tabs(tab_names)

    for idx, report in enumerate(result.agent_reports):
        with tabs[idx]:
            st.markdown(streamlit_markdown_text(report.analysis))

    with tabs[-1]:
        sources = result.enrichment_sources
        warnings = result.enrichment_warnings
        stats = result.enrichment_filter_stats
        st.markdown("### Enrichment Sources")
        if sources:
            for source in sources:
                st.markdown(f"- {source}")
        else:
            st.caption("No external enrichment sources captured.")
        st.markdown("### Enrichment Warnings")
        if warnings:
            for warning in warnings:
                st.warning(warning)
        else:
            st.caption("No enrichment warnings.")
        st.markdown("### Filter Stats")
        st.json(stats)


def _render_cached_report(path: Path) -> None:
    st.subheader(f"Cached Report: {path.name}")
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        st.error(f"Could not read cached report: {exc}")
        return

    pdf_path = path.with_suffix(".pdf")
    if pdf_path.exists():
        st.download_button(
            "Download Cached PDF",
            data=pdf_path.read_bytes(),
            file_name=pdf_path.name,
            mime="application/pdf",
            use_container_width=True,
        )
    st.markdown(streamlit_markdown_text(text))


def main() -> None:
    logging.basicConfig(
        format="%(levelname)s | %(name)s | %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    st.set_page_config(page_title="AI Financial Analyst", layout="wide")
    _bootstrap_env_from_streamlit_secrets()
    _init_sentry()
    st.title("AI Financial Analyst")
    st.caption("Multi-agent equity research with provider selection and context budgets.")

    with st.sidebar:
        st.header("Run Configuration")
        provider = st.selectbox(
            "LLM Provider",
            options=["openai", "anthropic"],
            index=0 if settings.llm_provider == "openai" else 1,
        )
        if provider == "openai":
            st.caption("Using default OpenAI model and deployment CBS key.")
        else:
            st.caption("Anthropic requires user-provided key for each run (BYOK).")
        anthropic_user_key = st.text_input(
            "Anthropic API key (required only for Anthropic runs)",
            type="password",
            help="Used only for the current run and not stored server-side.",
        )
        user_agent = st.text_input(
            "SEC User-Agent",
            value=settings.sec_user_agent,
        )

        st.subheader("Enrichment")
        enable_tiingo = st.checkbox("Enable Tiingo market data", value=settings.enable_tiingo)
        enable_fmp = st.checkbox("Enable FMP valuations & estimates", value=settings.enable_fmp)
        enable_yahoo = st.checkbox(
            "Enable Yahoo Finance fallback",
            value=settings.enable_yahoo,
            help="Unreliable on cloud IPs. Enable as fallback when Tiingo/FMP are unavailable.",
        )
        enable_tavily = st.checkbox("Enable Tavily research", value=settings.enable_tavily)

        with st.expander("Budget Guardrails", expanded=False):
            max_agent_context_chars = st.number_input(
                "MAX_AGENT_CONTEXT_CHARS",
                min_value=1000,
                max_value=20000,
                step=500,
                value=settings.max_agent_context_chars,
            )
            max_agent_output_tokens = st.number_input(
                "MAX_AGENT_OUTPUT_TOKENS",
                min_value=100,
                max_value=4000,
                step=100,
                value=settings.max_agent_output_tokens,
            )
            synthesis_report_max_chars = st.number_input(
                "SYNTHESIS_REPORT_MAX_CHARS",
                min_value=500,
                max_value=10000,
                step=250,
                value=settings.synthesis_report_max_chars,
            )
            synthesis_input_max_chars = st.number_input(
                "SYNTHESIS_INPUT_MAX_CHARS",
                min_value=1000,
                max_value=30000,
                step=500,
                value=settings.synthesis_input_max_chars,
            )
            max_synthesis_output_tokens = st.number_input(
                "MAX_SYNTHESIS_OUTPUT_TOKENS",
                min_value=100,
                max_value=5000,
                step=100,
                value=settings.max_synthesis_output_tokens,
            )

        st.divider()
        st.subheader("Report Viewer")
        cached_files = list_cached_reports(limit=50)
        view_mode = st.radio("View mode", options=["Current run", "Cached reports"], index=0)
        cached_options = [p.name for p in cached_files]
        selected_cached = st.selectbox(
            "Cached report file",
            options=cached_options if cached_options else ["(none)"],
            disabled=not cached_options,
        )

    ticker = st.text_input("Ticker", value="AAPL").strip().upper()

    if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
        try:
            from warehouse.db import WarehouseDB
            from warehouse.change_detector import incremental_update

            wh_db = WarehouseDB()
            tracked = wh_db.list_tracked_tickers()
            with st.sidebar:
                st.divider()
                with st.expander("Warehouse Status", expanded=False):
                    st.metric("Tracked Tickers", len(tracked))
                    if ticker.upper() in [t.upper() for t in tracked]:
                        company = wh_db.get_company(ticker.upper())
                        if company:
                            from datetime import datetime as _dt

                            if company.get("bootstrapped_at"):
                                bs_time = _dt.fromtimestamp(company["bootstrapped_at"]).strftime(
                                    "%Y-%m-%d %H:%M"
                                )
                                st.text(f"Bootstrapped: {bs_time}")
                            if company.get("last_checked_at"):
                                lc_time = _dt.fromtimestamp(company["last_checked_at"]).strftime(
                                    "%Y-%m-%d %H:%M"
                                )
                                st.text(f"Last checked: {lc_time}")
                    if st.button("Force Refresh", key="wh_refresh"):
                        try:
                            from sec.client import SECClient as SECCli

                            result = incremental_update(
                                ticker.upper(), wh_db, SECCli(user_agent=user_agent)
                            )
                            if result.had_changes:
                                st.success(
                                    f"Updated {ticker.upper()}: {result.new_filing_count} new filings"
                                )
                            else:
                                st.info(f"{ticker.upper()} is up to date")
                        except Exception as exc:
                            st.error(f"Refresh failed: {exc}")
        except Exception:
            pass

    col_run, col_hint = st.columns([1, 4])
    with col_run:
        run = st.button("Run Analysis", type="primary", use_container_width=True)
    with col_hint:
        st.caption("Tip: use CLI `--inspect-context` for no-LLM dry runs.")

    if run:
        if not ticker:
            st.error("Please enter a ticker symbol.")
            return

        _set_runtime_env(
            provider=provider,
            enable_yahoo=enable_yahoo,
            enable_tavily=enable_tavily,
            enable_tiingo=enable_tiingo,
            enable_fmp=enable_fmp,
            max_agent_context_chars=int(max_agent_context_chars),
            max_agent_output_tokens=int(max_agent_output_tokens),
            synthesis_report_max_chars=int(synthesis_report_max_chars),
            synthesis_input_max_chars=int(synthesis_input_max_chars),
            max_synthesis_output_tokens=int(max_synthesis_output_tokens),
        )

        if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            st.error("OpenAI provider selected but no API key is available.")
            st.info("Configure OPENAI_CBS_API_KEY in deployment secrets.")
            return
        if provider == "anthropic" and not anthropic_user_key.strip():
            st.error("Anthropic provider selected but no Anthropic key was provided.")
            st.info("Paste your Anthropic API key in the sidebar for this run.")
            return

        progress = st.status("Running analysis...", expanded=True)
        try:
            if provider == "anthropic":
                result = _with_ephemeral_env(
                    {"ANTHROPIC_API_KEY": anthropic_user_key.strip()},
                    lambda: _run_analysis_sync(ticker, user_agent, provider, "", progress),
                )
            else:
                result = _run_analysis_sync(ticker, user_agent, provider, "", progress)
            result_dict = result.model_dump()
            result_dict["agent_reports"] = [
                (r.agent_name, r.analysis) for r in result.agent_reports
            ]
            txt_path = save_report(result_dict)
            pdf_path = save_pdf_report(result_dict, filepath=txt_path.replace(".txt", ".pdf"))
            st.session_state["latest_result"] = result
            st.session_state["latest_txt_path"] = txt_path
            st.session_state["latest_pdf_path"] = pdf_path
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "Invalid API key" in msg or "AuthenticationError" in msg:
                st.error("Authentication failed with the selected provider key.")
                if provider == "anthropic":
                    st.info("Check ANTHROPIC_API_KEY in deployment secrets, or switch to OpenAI.")
                else:
                    st.info(
                        "Check OPENAI_CBS_API_KEY / OPENAI_API_KEY and OPENAI_BASE_URL in deployment secrets."
                    )
            progress.update(label=f"Failed: {exc}", state="error", expanded=True)
            st.exception(exc)
            return
        progress.update(label="Analysis complete", state="complete", expanded=False)

    if view_mode == "Cached reports":
        if not cached_options:
            st.info("No cached reports found yet in `reports/`.")
            return
        chosen = Path("reports") / selected_cached
        _render_cached_report(chosen)
        return

    latest_result = st.session_state.get("latest_result")
    if not latest_result:
        st.info("Run an analysis or switch to Cached reports in the sidebar.")
        return
    _render_result(
        latest_result,
        txt_path=st.session_state.get("latest_txt_path"),
        pdf_path=st.session_state.get("latest_pdf_path"),
    )


if __name__ == "__main__":
    main()

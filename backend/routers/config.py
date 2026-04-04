from fastapi import APIRouter
from backend.schemas import ConfigDefaults
from config import settings

router = APIRouter()


@router.get("/defaults", response_model=ConfigDefaults)
async def get_defaults():
    return ConfigDefaults(
        providers=["openai", "anthropic"],
        enable_tiingo=settings.enable_tiingo,
        enable_fmp=settings.enable_fmp,
        enable_yahoo=settings.enable_yahoo,
        enable_tavily=settings.enable_tavily,
        max_agent_context_chars=settings.max_agent_context_chars,
        max_agent_output_tokens=settings.max_agent_output_tokens,
        synthesis_report_max_chars=settings.synthesis_report_max_chars,
        synthesis_input_max_chars=settings.synthesis_input_max_chars,
        max_synthesis_output_tokens=settings.max_synthesis_output_tokens,
    )

import logging

from fastapi import APIRouter

from backend.schemas import SectorOverview
from market_enrichment import SECTOR_ETF_MAP

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/sectors")
async def list_sectors():
    sectors = []
    for sector, etf in SECTOR_ETF_MAP.items():
        if any(s["sector"] == sector for s in sectors):
            continue
        sectors.append(SectorOverview(
            sector=sector,
            etf_symbol=etf,
        ).model_dump())
    return {"sectors": sectors}


@router.get("/{sector}/overview")
async def sector_overview(sector: str):
    etf = SECTOR_ETF_MAP.get(sector, "")
    return SectorOverview(
        sector=sector,
        etf_symbol=etf,
    )


@router.get("/{sector}/peers")
async def sector_peers(sector: str, limit: int = 10):
    return {"sector": sector, "peers": [], "message": "Peer discovery for sector coming soon"}


@router.post("/{sector}/analyze")
async def analyze_sector(sector: str):
    return {"sector": sector, "message": "Sector analysis coming soon"}

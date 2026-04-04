import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)
router = APIRouter()

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


@router.get("/")
async def list_reports(limit: int = 50):
    if not REPORTS_DIR.exists():
        return {"reports": []}
    files = sorted(REPORTS_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "reports": [
            {
                "filename": f.name,
                "size": f.stat().st_size,
                "modified": f.stat().st_mtime,
                "has_pdf": f.with_suffix(".pdf").exists(),
            }
            for f in files[:limit]
        ]
    }


@router.get("/{filename}/pdf")
async def download_pdf(filename: str):
    pdf_name = filename.replace(".txt", ".pdf") if filename.endswith(".txt") else filename
    if not pdf_name.endswith(".pdf"):
        pdf_name += ".pdf"
    path = REPORTS_DIR / pdf_name
    if not path.exists() or not path.is_relative_to(REPORTS_DIR):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=pdf_name)


@router.get("/{filename}")
async def get_report_text(filename: str):
    path = REPORTS_DIR / filename
    if not path.exists() or not path.is_relative_to(REPORTS_DIR):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}

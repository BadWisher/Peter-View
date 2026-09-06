from __future__ import annotations

from pydantic import BaseModel

from typing import Any

from fastapi import APIRouter, Depends, Response
from ..auth import require_user
from ..report import generate_excel_report

router = APIRouter(tags=["Отчёты"])

class ReportRequest(BaseModel):
    issues: list[dict[str, Any]]
    source: str = ""


@router.post("/api/report-issues")
async def report_from_issues(body: ReportRequest, _user: str = Depends(require_user)):
    """xlsx из уже готовых issues (без повторной проверки)."""
    xlsx_bytes = generate_excel_report(body.issues, body.source)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="report.xlsx"'},
    )

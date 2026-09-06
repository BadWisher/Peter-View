from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from .. import audit
from ..auth import require_user
from ..checker import check_text
from ..crawler import crawl_site
from ..extractors import extract_from_file
from ..report import generate_excel_report
from .checks_shared import _check_text_chunked
from .infra import CHECK_TIMEOUT, MAX_UPLOAD_BYTES
from .checks_shared import _summary
from .infra import _check_sem
from .rules_store import _read_rules, _rules_for_check

router = APIRouter(tags=["Вычитка"])

@router.post("/api/check")
async def check_file(
    file: UploadFile = File(...),
    user_rules: str = Form(""),
    _user: str = Depends(require_user),
):
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")

    try:
        text = await extract_from_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not text.strip():
        raise HTTPException(400, "Не удалось извлечь текст из файла")

    rules = _rules_for_check(user_rules)
    issues = await _check_text_chunked(text, user_rules=rules)
    for issue in issues:
        issue["page_url"] = ""
    return {
        "source": file.filename,
        "text_length": len(text),
        "pages_checked": 1,
        "issues": issues,
        "summary": _summary(issues),
    }


@router.post("/api/check-url")
async def check_url_stream(
    url: str = Form(...),
    user_rules: str = Form(""),
    _user: str = Depends(require_user),
):
    """Обход сайта + проверка каждой страницы, результат через SSE."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL должен начинаться с http:// или https://")

    rules = _rules_for_check(user_rules)

    async def event_generator():
        all_issues: list[dict] = []
        pages_checked = 0

        async for page in crawl_site(url):
            pages_checked += 1
            logger.info("Page %d crawled: %s (%d chars)", pages_checked, page.url, len(page.text))
            yield {
                "event": "progress",
                "data": json.dumps({
                    "pages_checked": pages_checked,
                    "current_url": page.url,
                }, ensure_ascii=False),
            }

            try:
                logger.info("Checking page %d: %s", pages_checked, page.url)
                async with _check_sem:
                    page_issues = await asyncio.wait_for(
                        check_text(page.text, user_rules=rules),
                        timeout=CHECK_TIMEOUT,
                    )
                logger.info("Page %d checked: %d issues", pages_checked, len(page_issues))
                for issue in page_issues:
                    issue["page_url"] = page.url
                all_issues.extend(page_issues)
            except asyncio.TimeoutError:
                logger.warning("check_text timeout for %s", page.url)

        result = {
            "source": url,
            "pages_checked": pages_checked,
            "issues": all_issues,
            "summary": _summary(all_issues),
        }
        if pages_checked == 0:
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": "Не удалось загрузить ни одной страницы. Проверь URL и доступность сайта с сервера.",
                }, ensure_ascii=False),
            }
            return

        yield {
            "event": "done",
            "data": json.dumps(result, ensure_ascii=False),
        }

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/check-text")
async def check_raw_text(
    text: str = Form(...),
    user_rules: str = Form(""),
    _user: str = Depends(require_user),
):
    if not text.strip():
        raise HTTPException(400, "Текст пустой")
    if len(text) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Текст слишком большой")

    rules = _rules_for_check(user_rules)
    issues = await _check_text_chunked(text, user_rules=rules)
    for issue in issues:
        issue["page_url"] = ""
    return {
        "source": "Текст",
        "text_length": len(text),
        "pages_checked": 1,
        "issues": issues,
        "summary": _summary(issues),
    }


@router.post("/api/report")
async def download_report(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    _user: str = Depends(require_user),
):
    """Проверка файла/текста → xlsx. Для URL используйте /api/report-issues."""
    source_name = ""
    all_issues: list[dict] = []

    if file and file.filename:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Файл слишком большой")
        extracted = await extract_from_file(content, file.filename)
        source_name = file.filename
        all_issues = await _check_text_chunked(extracted, user_rules=_read_rules())
        for issue in all_issues:
            issue["page_url"] = ""

    elif text:
        source_name = "Текст"
        all_issues = await _check_text_chunked(text, user_rules=_read_rules())
        for issue in all_issues:
            issue["page_url"] = ""

    else:
        raise HTTPException(400, "Укажи файл или текст")

    xlsx_bytes = generate_excel_report(all_issues, source_name)

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="report.xlsx"'},
    )

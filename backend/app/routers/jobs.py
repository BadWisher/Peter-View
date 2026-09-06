from __future__ import annotations

import asyncio
import copy
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from ..auth import require_user
from ..llm import jobs as llm_jobs
from ..llm import styleguide_store
from ..llm.documents import parse_file, parse_txt, parse_url
from .infra import MAX_UPLOAD_BYTES
from .session import _get_user_styleguide_id

router = APIRouter(tags=["Задачи"])

@router.post("/api/jobs")
async def create_job(
    file: UploadFile | None = File(None),
    url: str = Form(""),
    text: str = Form(""),
    styleguide_id: str = Form(""),
    check_language: bool = Form(True),
    check_styleguide: bool = Form(True),
    check_consistency: bool = Form(True),
    prompt: str = Form(""),
    user: str = Depends(require_user),
):
    """Ставит документ в очередь LLM-вычитки и возвращает job_id."""
    guide_id = styleguide_id.strip() or _get_user_styleguide_id(user)
    guide = styleguide_store.get_guide(guide_id)
    if guide is None:
        guide = styleguide_store.get_guide(styleguide_store.DEFAULT_ID)
    if guide is None:
        raise HTTPException(400, "Style Guide не найден")
    if not any((check_language, check_styleguide, check_consistency)):
        raise HTTPException(400, "Выбери хотя бы один тип проверки")
    prompt = prompt.strip()
    if len(prompt) > 4000:
        raise HTTPException(400, "Дополнительная инструкция слишком длинная")
    if prompt:
        guide = copy.deepcopy(guide)
        guide.extra_instruction = prompt

    if file and file.filename:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(400, "Файл пустой")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")
        try:
            document = parse_file(content, file.filename)
        except ValueError as e:
            raise HTTPException(400, str(e))
    elif text.strip():
        if len(text) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Текст слишком большой")
        document = parse_txt(text, source="Текст")
    elif url.strip():
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "URL должен начинаться с http:// или https://")
        try:
            document = await parse_url(url.strip())
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Не удалось загрузить страницу: {e}")
    else:
        raise HTTPException(400, "Укажи файл, текст или URL")

    if not document.blocks:
        raise HTTPException(400, "Не удалось извлечь текст из документа")

    job_id = llm_jobs.submit(
        document,
        guide,
        user=user,
        options={
            "language": check_language,
            "styleguide": check_styleguide,
            "consistency": check_consistency,
        },
    )
    return {"job_id": job_id}


@router.get("/api/jobs/{job_id}")
async def job_status(job_id: str, user: str = Depends(require_user)):
    job = llm_jobs.get_job(job_id)
    if job is None or (job.user and job.user != user):
        raise HTTPException(404, "Задача не найдена")
    return {"job_id": job.id, "status": job.status, "stage": job.stage, "error": job.error}


@router.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request, user: str = Depends(require_user)):
    """SSE-поток живого вывода воркеров: события start/delta/end/finished."""
    job = llm_jobs.get_job(job_id)
    if job is None or (job.user and job.user != user):
        raise HTTPException(404, "Задача не найдена")

    async def gen():
        sent_len: dict[int, int] = {}
        started: set[int] = set()
        ended: set[int] = set()

        def pending() -> bool:
            for pid in list(job.stream_order):
                block = job.stream_blocks.get(pid)
                if block is None:
                    continue
                if pid not in started:
                    return True
                if sent_len.get(pid, 0) < len(block["text"]):
                    return True
                if block["status"] != "running" and pid not in ended:
                    return True
            return job.status in ("done", "error")

        while True:
            if await request.is_disconnected():
                break
            for pid in list(job.stream_order):
                block = job.stream_blocks.get(pid)
                if block is None:
                    continue
                if pid not in started:
                    started.add(pid)
                    yield {"event": "start", "data": json.dumps(
                        {"id": pid, "worker": block["worker"], "scope": block["scope"]},
                        ensure_ascii=False)}
                text = block["text"]
                sl = sent_len.get(pid, 0)
                if sl > len(text):  # текст обрезали с начала — досылать нечего
                    sl = len(text)
                if len(text) > sl:
                    yield {"event": "delta", "data": json.dumps(
                        {"id": pid, "text": text[sl:]}, ensure_ascii=False)}
                    sent_len[pid] = len(text)
                if block["status"] != "running" and pid not in ended:
                    ended.add(pid)
                    yield {"event": "end", "data": json.dumps(
                        {"id": pid, "status": block["status"], "found": block.get("found"),
                         "error": block.get("error")},
                        ensure_ascii=False)}
            if job.status in ("done", "error"):
                yield {"event": "finished", "data": json.dumps(
                    {"status": job.status, "error": job.error}, ensure_ascii=False)}
                break
            wakeup = job.stream_wakeup
            if wakeup is None:
                await asyncio.sleep(0.05)
                continue
            if pending():
                await asyncio.sleep(0)
                continue
            wakeup.clear()
            if pending():
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(wakeup.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                pass

    return EventSourceResponse(
        gen(),
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/jobs/{job_id}/report")
async def job_report(job_id: str, user: str = Depends(require_user)):
    job = llm_jobs.get_job(job_id)
    if job is None or (job.user and job.user != user):
        raise HTTPException(404, "Задача не найдена")
    if job.status == "error":
        raise HTTPException(500, job.error or "Ошибка вычитки")
    if job.status != "done" or job.report is None:
        raise HTTPException(409, "Отчёт ещё не готов")
    return job.report

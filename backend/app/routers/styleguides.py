from __future__ import annotations

from pydantic import BaseModel

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from .. import audit
from ..auth import require_admin, require_user
from ..llm import extract_jobs
from ..llm import rag as llm_rag
from ..llm import styleguide_store
from ..llm.documents import parse_docx, parse_file
from .infra import MAX_UPLOAD_BYTES
from .session import _get_user_styleguide_id, _set_user_styleguide_id

router = APIRouter(tags=["Style Guide"])

# --- Style Guide ------------------------------------------------------------

class StyleGuideSaveRequest(BaseModel):
    name: str
    rules: list[dict[str, Any]]
    lexicon: dict[str, Any] | None = None


class StyleGuideUpdateRequest(BaseModel):
    name: str | None = None
    rules: list[dict[str, Any]] | None = None
    lexicon: dict[str, Any] | None = None


def _guide_meta(guide, selected_id: str) -> dict:
    return {
        "id": guide.id,
        "name": guide.name,
        "rule_count": len(guide.rules),
        "lexicon_count": len(guide.lexicon_forbidden) + len(guide.lexicon_allowed),
        "builtin": guide.builtin,
        "source_filename": guide.source_filename,
        "created_at": guide.created_at,
        "updated_at": guide.updated_at,
        "created_by": guide.created_by,
        "selected": guide.id == selected_id,
    }


@router.get("/api/styleguides")
async def list_styleguides(user: str = Depends(require_user)):
    selected = _get_user_styleguide_id(user)
    guides = styleguide_store.list_guides()
    return {"styleguides": [_guide_meta(g, selected) for g in guides], "selected": selected}


@router.get("/api/styleguides/current")
async def current_styleguide(user: str = Depends(require_user)):
    return {"selected": _get_user_styleguide_id(user)}


@router.get("/api/styleguides/{guide_id}")
async def get_styleguide(guide_id: str, user: str = Depends(require_user)):
    guide = styleguide_store.get_guide(guide_id)
    if guide is None:
        raise HTTPException(404, "Style Guide не найден")
    return {
        **_guide_meta(guide, _get_user_styleguide_id(user)),
        "rules": guide.rules,
        "lexicon": guide.lexicon or {"forbidden": [], "allowed": []},
    }


@router.get("/api/styleguides/{guide_id}/index-status")
async def styleguide_index_status(guide_id: str, user: str = Depends(require_user)):
    """Режим поиска по гайду: hybrid (семантика + слова) или lexical_only (только слова)."""
    guide = styleguide_store.get_guide(guide_id)
    if guide is None:
        raise HTTPException(404, "Style Guide не найден")
    state = await asyncio.to_thread(llm_rag.retrieval_state, guide)
    return {
        "guide_id": guide_id,
        "status": state["index_status"],
        "fallback_tier": state["fallback_tier"],
        "error": state["index_error"],
    }


@router.post("/api/styleguides/extract")
async def extract_styleguide(
    file: UploadFile = File(...),
    user: str = Depends(require_admin),
):
    """Загрузка docx -> фоновое извлечение правил. Возвращает job_id для опроса."""
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")

    ext = Path(file.filename).suffix.lower()
    try:
        if ext == ".docx":
            document = parse_docx(content, source=file.filename)
        else:
            document = parse_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not document.full_plain().strip():
        raise HTTPException(400, "Не удалось извлечь текст из документа")

    job_id = extract_jobs.submit(document, file.filename, content)
    return {"job_id": job_id}


@router.get("/api/styleguides/extract/{job_id}")
async def extract_styleguide_status(job_id: str, _user: str = Depends(require_admin)):
    job = extract_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    payload = {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "error": job.error,
        "source_filename": job.source_filename,
    }
    if job.status == "done":
        payload["rules"] = job.rules or []
        payload["lexicon"] = job.lexicon or {"forbidden": [], "allowed": []}
        payload["warning"] = job.warning
        payload["diagnostics"] = job.diagnostics or {}
    return payload


@router.post("/api/styleguides")
async def create_styleguide(body: StyleGuideSaveRequest, user: str = Depends(require_admin)):
    try:
        guide = styleguide_store.save_guide(
            body.name, body.rules, created_by=user, lexicon=body.lexicon
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.append("guide_create", user, guide=guide.id)
    return _guide_meta(guide, _get_user_styleguide_id(user))


@router.put("/api/styleguides/{guide_id}")
async def update_styleguide(guide_id: str, body: StyleGuideUpdateRequest, user: str = Depends(require_admin)):
    try:
        guide = styleguide_store.update_guide(
            guide_id, name=body.name, rules=body.rules, lexicon=body.lexicon
        )
    except KeyError:
        raise HTTPException(404, "Style Guide не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.append("guide_update", user, guide=guide_id)
    return {
        **_guide_meta(guide, _get_user_styleguide_id(user)),
        "rules": guide.rules,
        "lexicon": guide.lexicon or {"forbidden": [], "allowed": []},
    }


@router.delete("/api/styleguides/{guide_id}")
async def delete_styleguide(guide_id: str, user: str = Depends(require_admin)):
    try:
        deleted = styleguide_store.delete_guide(guide_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    if not deleted:
        raise HTTPException(404, "Style Guide не найден")

    if _get_user_styleguide_id(user) == guide_id:
        _set_user_styleguide_id(user, styleguide_store.DEFAULT_ID)
    audit.append("guide_delete", user, guide=guide_id)
    return {"ok": True}


@router.post("/api/styleguides/{guide_id}/select")
async def select_styleguide(guide_id: str, user: str = Depends(require_user)):
    if styleguide_store.get_guide(guide_id) is None:
        raise HTTPException(404, "Style Guide не найден")
    _set_user_styleguide_id(user, guide_id)
    return {"ok": True, "selected": guide_id}


# --- Настройки проверки (глобальные, только для админов) --------------------

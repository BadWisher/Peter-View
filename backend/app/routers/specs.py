from __future__ import annotations

from pydantic import BaseModel

import asyncio
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from ..auth import require_user
from ..llm import api_review, api_specs
from ..llm import jobs as llm_jobs
from ..llm import openapi_fields

router = APIRouter(tags=["Спецификации API"])

class ApiSpecCreate(BaseModel):
    name: str
    ru_doc_id: str
    en_doc_id: str


class ApiSpecPatch(BaseModel):
    name: str | None = None
    ru_doc_id: str | None = None
    en_doc_id: str | None = None


def _spec_summary(spec: dict) -> dict:
    ru = api_specs.doc_meta(spec["ru_doc_id"])
    en = api_specs.doc_meta(spec["en_doc_id"])
    return {
        "id": spec["id"],
        "name": spec["name"],
        "created_by": spec.get("created_by", ""),
        "created_at": spec.get("created_at", 0),
        "ru": ru,
        "en": en,
        "has_previous": api_specs.has_diff_baseline(spec["ru_doc_id"]),
    }


def _spec_or_404(spec_id: str) -> dict:
    spec = api_specs.get_spec(spec_id)
    if spec is None:
        raise HTTPException(404, "Связка не найдена")
    return spec


def _build_segments(spec: dict, page: int, size: int, q: str = "") -> dict:
    ru_latest, ru_num, _, _ = api_specs.latest_and_previous(spec["ru_doc_id"])
    en_latest, en_num, _, _ = api_specs.latest_and_previous(spec["en_doc_id"])
    ru_fields = openapi_fields.extract_fields(ru_latest)
    en_fields = openapi_fields.extract_fields(en_latest)
    rows = openapi_fields.pair_fields(ru_fields, en_fields)
    q = (q or "").strip()
    if q:
        ql = q.casefold()
        rows = [
            r for r in rows
            if ql in (r.get("context") or "").casefold()
            or ql in (r.get("ru_text") or "").casefold()
            or ql in (r.get("en_text") or "").casefold()
            or ql in (r.get("path_str") or "").casefold()
        ]
    total = len(rows)
    start = page * size
    return {
        "total": total,
        "page": page,
        "size": size,
        "query": q,
        "ru_version": ru_num,
        "en_version": en_num,
        "segments": rows[start:start + size],
    }


def _build_diff(spec: dict) -> dict:
    latest, lnum, prev, pnum = api_specs.diff_versions(spec["ru_doc_id"])
    if prev is None:
        return {"has_previous": False, "from_version": None, "to_version": lnum, "changes": []}
    new_fields = openapi_fields.extract_fields(latest)
    old_fields = openapi_fields.extract_fields(prev)
    changes = openapi_fields.diff_fields(old_fields, new_fields)
    # подтянем текущий EN-текст к изменённым RU-полям для контекста/перевода
    en_latest, _, _, _ = api_specs.latest_and_previous(spec["en_doc_id"])
    en_by_path = {f["path_str"]: f["text"] for f in openapi_fields.extract_fields(en_latest)}
    for c in changes:
        c["en_text"] = en_by_path.get(c["path_str"])
    return {"has_previous": True, "from_version": pnum, "to_version": lnum, "changes": changes}

@router.get("/api/api-specs")
async def api_list_specs(_user: str = Depends(require_user)):
    return {"specs": [_spec_summary(s) for s in api_specs.list_specs()]}


@router.get("/api/api-spec-documents")
async def api_spec_documents(_user: str = Depends(require_user)):
    """Документы репозитория для выбора RU/EN при создании связки."""
    return {"documents": api_specs.documents_for_picker()}


@router.post("/api/api-specs")
async def api_create_spec(body: ApiSpecCreate, user: str = Depends(require_user)):
    try:
        spec = api_specs.create_spec(body.name, body.ru_doc_id, body.en_doc_id, created_by=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _spec_summary(spec)


@router.patch("/api/api-specs/{spec_id}")
async def api_patch_spec(spec_id: str, body: ApiSpecPatch, _user: str = Depends(require_user)):
    try:
        spec = api_specs.update_spec(spec_id, body.name, body.ru_doc_id, body.en_doc_id)
    except KeyError:
        raise HTTPException(404, "Связка не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _spec_summary(spec)


@router.delete("/api/api-specs/{spec_id}")
async def api_delete_spec(spec_id: str, _user: str = Depends(require_user)):
    try:
        api_specs.delete_spec(spec_id)
    except KeyError:
        raise HTTPException(404, "Связка не найдена")
    return {"ok": True}


@router.get("/api/api-specs/{spec_id}/segments")
async def api_spec_segments(spec_id: str, page: int = 0, size: int = 25, q: str = "", _user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)
    page = max(0, page)
    size = max(1, min(size, 250))
    try:
        return await asyncio.to_thread(_build_segments, spec, page, size, q)
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _build_consistency(spec: dict, lang: str) -> dict:
    doc_id = spec["ru_doc_id"] if lang == "ru" else spec["en_doc_id"]
    latest, num, _, _ = api_specs.latest_and_previous(doc_id)
    fields = openapi_fields.extract_fields(latest)
    report = openapi_fields.consistency_report(fields)
    report["lang"] = lang
    report["version"] = num
    return report


@router.get("/api/api-specs/{spec_id}/consistency")
async def api_spec_consistency(spec_id: str, lang: str = "ru", _user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)
    lang = "en" if lang == "en" else "ru"
    try:
        return await asyncio.to_thread(_build_consistency, spec, lang)
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/api-specs/{spec_id}/diff")
async def api_spec_diff(spec_id: str, _user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)
    try:
        return await asyncio.to_thread(_build_diff, spec)
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _diff_changes(spec: dict) -> list[dict]:
    latest, _, prev, _ = api_specs.diff_versions(spec["ru_doc_id"])
    if prev is None:
        return []
    new_fields = openapi_fields.extract_fields(latest)
    old_fields = openapi_fields.extract_fields(prev)
    return openapi_fields.diff_fields(old_fields, new_fields)


@router.post("/api/api-specs/{spec_id}/ai-review")
async def api_spec_ai_review(spec_id: str, user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)

    async def runner(progress):
        progress("Готовлю дифф")
        changes = await asyncio.to_thread(_diff_changes, spec)
        if not changes:
            return {"type": "api-review", "changed": 0, "issues": [],
                    "message": "Изменений для проверки нет"}
        progress(f"Проверка изменений: {len(changes)}")
        issues = await api_review.review_segments(changes)
        return {"type": "api-review", "changed": len(changes), "issues": issues}

    job_id = llm_jobs.submit_task(f"api-review:{spec['name']}", runner, user=user)
    return {"job_id": job_id}


@router.post("/api/api-specs/{spec_id}/translate")
async def api_spec_translate(spec_id: str, user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)

    async def runner(progress):
        progress("Готовлю дифф")
        changes = await asyncio.to_thread(_diff_changes, spec)
        if not changes:
            return {"type": "api-translate", "changed": 0, "translations": [],
                    "message": "Изменений для перевода нет"}
        progress(f"Перевожу изменения: {len(changes)}")
        mapping = await api_review.translate_segments(changes)
        translations = [
            {
                "path_str": c["path_str"],
                "context": c["context"],
                "ru_text": c["new_text"],
                "en_text": mapping.get(c["path_str"], ""),
            }
            for c in changes
        ]
        return {"type": "api-translate", "changed": len(changes), "translations": translations}

    job_id = llm_jobs.submit_task(f"api-translate:{spec['name']}", runner, user=user)
    return {"job_id": job_id}


class ApiEdits(BaseModel):
    target: str  # "ru" | "en"
    edits: dict[str, str]


@router.post("/api/api-specs/{spec_id}/download")
async def api_spec_download(spec_id: str, body: ApiEdits, _user: str = Depends(require_user)):
    """Применяет правки к последней версии RU/EN и отдаёт исправленный YAML файлом."""
    from urllib.parse import quote
    spec = _spec_or_404(spec_id)
    doc_id = spec["ru_doc_id"] if body.target == "ru" else spec["en_doc_id"]
    meta = api_specs.doc_meta(doc_id)
    try:
        latest, _, _, _ = api_specs.latest_and_previous(doc_id)
        data = await asyncio.to_thread(openapi_fields.apply_edits, latest, body.edits or {})
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    base = (meta["filename"] if meta and meta.get("filename") else f"{body.target}.yaml")
    name = base.rsplit(".", 1)[0] + "_edited." + (base.rsplit(".", 1)[1] if "." in base else "yaml")
    ascii_name = name.encode("ascii", "ignore").decode() or "edited.yaml"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(content=data, media_type="application/x-yaml",
                    headers={"Content-Disposition": disposition})

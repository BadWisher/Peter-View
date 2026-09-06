from __future__ import annotations

from pydantic import BaseModel

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from ..auth import require_user
from ..llm import repo_store
from ..llm import stats as llm_stats

router = APIRouter(tags=["Репозиторий"])

class FolderCreate(BaseModel):
    name: str
    parent_id: str | None = None

def _doc_summary(doc: dict, views: dict[str, float] | None = None) -> dict:
    versions = doc.get("versions", [])
    latest = versions[-1] if versions else {}
    last_activity = doc.get("last_activity_at", 0)
    seen_at = (views or {}).get(doc["id"], 0)
    return {
        "id": doc["id"],
        "name": doc["name"],
        "folder_id": doc.get("folder_id"),
        "archived": bool(doc.get("archived")),
        "version_count": len(versions),
        "created_by": doc.get("created_by", ""),
        "created_at": doc.get("created_at", 0),
        "last_activity_at": last_activity,
        "is_new": views is not None and last_activity > seen_at,
        "latest": {
            "number": latest.get("number"),
            "uploaded_by": latest.get("uploaded_by", ""),
            "note": latest.get("note", ""),
            "jira": latest.get("jira", ""),
            "created_at": latest.get("created_at", 0),
            "filename": latest.get("filename", ""),
        } if latest else None,
    }


def _folder_summary(folder: dict) -> dict:
    sub = len(repo_store.list_child_folders(folder["id"]))
    docs = len(repo_store.list_documents(folder["id"]))
    return {
        "id": folder["id"],
        "name": folder["name"],
        "parent_id": folder.get("parent_id"),
        "created_by": folder.get("created_by", ""),
        "created_at": folder.get("created_at", 0),
        "item_count": sub + docs,
    }

async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > repo_store.MAX_FILE_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {repo_store.MAX_FILE_BYTES // 1024 // 1024} МБ)")
    return content

@router.get("/api/repo/folders")
async def repo_list_folder(parent: str = "", user: str = Depends(require_user)):
    folder_id = parent.strip() or None
    if folder_id in ("root", "null"):
        folder_id = None
    if folder_id and not repo_store.breadcrumbs(folder_id):
        raise HTTPException(404, "Папка не найдена")
    views = llm_stats.last_views(user)
    return {
        "folder_id": folder_id,
        "breadcrumbs": repo_store.breadcrumbs(folder_id),
        "folders": [_folder_summary(f) for f in repo_store.list_child_folders(folder_id)],
        "documents": [_doc_summary(d, views) for d in repo_store.list_documents(folder_id)],
    }


@router.get("/api/repo/archived")
async def repo_archived(user: str = Depends(require_user)):
    views = llm_stats.last_views(user)
    return {"documents": [_doc_summary(d, views) for d in repo_store.list_archived()]}


@router.get("/api/repo/search")
async def repo_search(q: str = "", user: str = Depends(require_user)):
    views = llm_stats.last_views(user)
    return {"documents": [_doc_summary(d, views) for d in repo_store.search(q)]}


@router.get("/api/repo/tree")
async def repo_tree(_user: str = Depends(require_user)):
    """Плоский список всех папок для выбора при перемещении."""
    return {"folders": repo_store.all_folders()}


@router.get("/api/repo/usage")
async def repo_usage(_user: str = Depends(require_user)):
    return repo_store.usage()


@router.post("/api/repo/folders")
async def repo_create_folder(body: FolderCreate, user: str = Depends(require_user)):
    try:
        folder = repo_store.create_folder(body.name, body.parent_id, created_by=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _folder_summary(folder)


@router.delete("/api/repo/folders/{folder_id}")
async def repo_delete_folder(folder_id: str, _user: str = Depends(require_user)):
    try:
        repo_store.delete_folder(folder_id)
    except KeyError:
        raise HTTPException(404, "Папка не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}

class RepoDocPatch(BaseModel):
    name: str | None = None
    folder_id: str | None = None
    move: bool = False  # отличить «перенести в корень» (folder_id=None) от «не трогать»


class RepoFolderPatch(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    move: bool = False


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > repo_store.MAX_FILE_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {repo_store.MAX_FILE_BYTES // 1024 // 1024} МБ)")
    return content


@router.post("/api/repo/documents")
async def repo_create_document(
    file: UploadFile = File(...),
    folder_id: str = Form(""),
    name: str = Form(""),
    note: str = Form(""),
    jira: str = Form(""),
    user: str = Depends(require_user),
):
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")
    content = await _read_upload(file)
    try:
        doc = repo_store.create_document(
            folder_id.strip() or None, name, file.filename, content,
            uploaded_by=user, note=note, jira=jira,
        )
    except repo_store.QuotaError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _doc_summary(doc)

@router.get("/api/repo/documents/{doc_id}")
async def repo_get_document(doc_id: str, user: str = Depends(require_user)):
    doc = repo_store.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    llm_stats.mark_seen(user, doc_id)
    return doc


@router.patch("/api/repo/documents/{doc_id}")
async def repo_patch_document(doc_id: str, body: RepoDocPatch, user: str = Depends(require_user)):
    try:
        doc = repo_store.get_document(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if body.name is not None:
            doc = repo_store.rename_document(doc_id, body.name)
        if body.move:
            doc = repo_store.move_document(doc_id, body.folder_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _doc_summary(doc, llm_stats.last_views(user))


@router.patch("/api/repo/folders/{folder_id}")
async def repo_patch_folder(folder_id: str, body: RepoFolderPatch, _user: str = Depends(require_user)):
    try:
        if body.name is not None:
            repo_store.rename_folder(folder_id, body.name)
        if body.move:
            repo_store.move_folder(folder_id, body.parent_id)
    except KeyError:
        raise HTTPException(404, "Папка не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    folder = repo_store.get_folder(folder_id)
    if folder is None:
        raise HTTPException(404, "Папка не найдена")
    return _folder_summary(folder)


@router.post("/api/repo/documents/{doc_id}/versions")
async def repo_add_version(
    doc_id: str,
    file: UploadFile = File(...),
    note: str = Form(""),
    jira: str = Form(""),
    kind: str = Form("upload"),
    user: str = Depends(require_user),
):
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")
    content = await _read_upload(file)
    try:
        doc = repo_store.add_version(
            doc_id, file.filename, content, uploaded_by=user, note=note, jira=jira,
            kind=("review" if kind == "review" else "upload"),
        )
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    except repo_store.QuotaError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _doc_summary(doc)


@router.get("/api/repo/documents/{doc_id}/versions/{number}")
async def repo_download_version(doc_id: str, number: int, _user: str = Depends(require_user)):
    from urllib.parse import quote
    try:
        filename, data = repo_store.version_bytes(doc_id, number)
    except KeyError:
        raise HTTPException(404, "Версия не найдена")
    ascii_name = filename.encode("ascii", "ignore").decode() or f"v{number}"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.post("/api/repo/documents/{doc_id}/archive")
async def repo_archive(doc_id: str, _user: str = Depends(require_user)):
    try:
        doc = repo_store.archive_document(doc_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    return _doc_summary(doc)


@router.post("/api/repo/documents/{doc_id}/unarchive")
async def repo_unarchive(doc_id: str, _user: str = Depends(require_user)):
    try:
        doc = repo_store.unarchive_document(doc_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    return _doc_summary(doc)


@router.delete("/api/repo/documents/{doc_id}")
async def repo_delete_document(doc_id: str, _user: str = Depends(require_user)):
    try:
        repo_store.delete_document(doc_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    return {"ok": True}


# --- Вычитка API: связки RU/EN документов OpenAPI -----------------------------

"""Файловое хранилище репозитория документов на вычитку.

Структура на томе backend-data (REPO_STORE_DIR, по умолчанию /app/data/repo):
- folders.json            — дерево папок (поддерживается вложенность)
- docs/<doc_id>.json      — документ + история версий + флаг архива
- blobs/<doc_id>/<n>.bin  — байты версии активного документа
- blobs/<doc_id>/archive.zip — версии заархивированного документа (поштучные .bin удаляются)

Репозиторий общий для всех пользователей. Каждая новая версия — это «передача»
документа: кто загрузил, заметка и ссылка на задачу Jira.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_DIR = Path(os.getenv("REPO_STORE_DIR", "/app/data/repo"))
MAX_FILE_BYTES = int(os.getenv("REPO_MAX_FILE_BYTES", str(25 * 1024 * 1024)))
ARCHIVE_AFTER_DAYS = int(os.getenv("REPO_ARCHIVE_AFTER_DAYS", "90"))
JIRA_PROJECT = os.getenv("REPO_JIRA_PROJECT", "")

_lock = threading.RLock()


class QuotaError(Exception):
    """Превышен лимит хранилища."""


# --- пути и утилиты ---------------------------------------------------------

# Идентификаторы документов генерируются как uuid4().hex[:12]. Жёстко
# ограничиваем набор символов, чтобы исключить path traversal (`..`, `/`,
# абсолютные пути): из URL приходит только то, что подставляется в путь.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(doc_id: str) -> str:
    if not isinstance(doc_id, str) or not _ID_RE.fullmatch(doc_id):
        raise ValueError(f"Недопустимый идентификатор документа: {doc_id!r}")
    return doc_id


def _folders_file() -> Path:
    return REPO_DIR / "folders.json"


def _doc_path(doc_id: str) -> Path:
    return REPO_DIR / "docs" / f"{_safe_id(doc_id)}.json"


def _blob_dir(doc_id: str) -> Path:
    return REPO_DIR / "blobs" / _safe_id(doc_id)


def _archive_path(doc_id: str) -> Path:
    return _blob_dir(doc_id) / "archive.zip"


def _ensure_dirs() -> None:
    (REPO_DIR / "docs").mkdir(parents=True, exist_ok=True)
    (REPO_DIR / "blobs").mkdir(parents=True, exist_ok=True)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize_jira(raw: str) -> str:
    """Нормализует ключ задачи (PROJ-123). Пустую строку оставляет пустой."""
    s = (raw or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"([A-Za-z]+)-?(\d+)", s)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    if s.isdigit() and JIRA_PROJECT:
        return f"{JIRA_PROJECT}-{s}"
    return s


# --- папки ------------------------------------------------------------------

def _read_folders() -> list[dict]:
    path = _folders_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_folders(folders: list[dict]) -> None:
    _ensure_dirs()
    _folders_file().write_text(
        json.dumps(folders, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def create_folder(name: str, parent_id: str | None, created_by: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажи название папки")
    with _lock:
        folders = _read_folders()
        if parent_id and not any(f["id"] == parent_id for f in folders):
            raise ValueError("Родительская папка не найдена")
        folder = {
            "id": _new_id(),
            "name": name,
            "parent_id": parent_id or None,
            "created_by": created_by,
            "created_at": time.time(),
        }
        folders.append(folder)
        _write_folders(folders)
    return folder


def breadcrumbs(folder_id: str | None) -> list[dict]:
    """Цепочка от корня до текущей папки: [{id, name}, ...] (без корня)."""
    if not folder_id:
        return []
    folders = {f["id"]: f for f in _read_folders()}
    chain: list[dict] = []
    seen: set[str] = set()
    cur = folder_id
    while cur and cur in folders and cur not in seen:
        seen.add(cur)
        f = folders[cur]
        chain.append({"id": f["id"], "name": f["name"]})
        cur = f.get("parent_id")
    chain.reverse()
    return chain


def get_folder(folder_id: str) -> dict | None:
    return next((f for f in _read_folders() if f["id"] == folder_id), None)


def all_folders() -> list[dict]:
    folders = _read_folders()
    folders.sort(key=lambda f: f["name"].lower())
    return [
        {"id": f["id"], "name": f["name"], "parent_id": f.get("parent_id")}
        for f in folders
    ]


def list_child_folders(parent_id: str | None) -> list[dict]:
    folders = _read_folders()
    children = [f for f in folders if f.get("parent_id") == (parent_id or None)]
    children.sort(key=lambda f: f["name"].lower())
    return children


def delete_folder(folder_id: str) -> None:
    with _lock:
        folders = _read_folders()
        if not any(f["id"] == folder_id for f in folders):
            raise KeyError(folder_id)
        if any(f.get("parent_id") == folder_id for f in folders):
            raise ValueError("Папка не пуста (есть вложенные папки)")
        if any(d.get("folder_id") == folder_id for d in _all_docs()):
            raise ValueError("Папка не пуста (есть документы)")
        _write_folders([f for f in folders if f["id"] != folder_id])


def _descendant_folder_ids(folder_id: str, folders: list[dict]) -> set[str]:
    """Сам folder_id и все вложенные в него папки (для запрета переноса в себя)."""
    result = {folder_id}
    changed = True
    while changed:
        changed = False
        for f in folders:
            if f.get("parent_id") in result and f["id"] not in result:
                result.add(f["id"])
                changed = True
    return result


def rename_folder(folder_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажи название папки")
    with _lock:
        folders = _read_folders()
        folder = next((f for f in folders if f["id"] == folder_id), None)
        if folder is None:
            raise KeyError(folder_id)
        folder["name"] = name
        _write_folders(folders)
    return folder


def move_folder(folder_id: str, new_parent_id: str | None) -> dict:
    new_parent_id = new_parent_id or None
    with _lock:
        folders = _read_folders()
        folder = next((f for f in folders if f["id"] == folder_id), None)
        if folder is None:
            raise KeyError(folder_id)
        if new_parent_id is not None:
            if not any(f["id"] == new_parent_id for f in folders):
                raise ValueError("Целевая папка не найдена")
            if new_parent_id in _descendant_folder_ids(folder_id, folders):
                raise ValueError("Нельзя переместить папку внутрь самой себя")
        folder["parent_id"] = new_parent_id
        _write_folders(folders)
    return folder


# --- документы --------------------------------------------------------------

def _read_doc(doc_id: str) -> dict | None:
    try:
        path = _doc_path(doc_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("id") else None


def _write_doc(doc: dict) -> None:
    _ensure_dirs()
    _doc_path(doc["id"]).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _all_docs() -> list[dict]:
    docs_dir = REPO_DIR / "docs"
    if not docs_dir.exists():
        return []
    out: list[dict] = []
    for path in docs_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            out.append(data)
    return out


def get_document(doc_id: str) -> dict | None:
    return _read_doc(doc_id)


def list_documents(folder_id: str | None) -> list[dict]:
    docs = [
        d for d in _all_docs()
        if d.get("folder_id") == (folder_id or None) and not d.get("archived")
    ]
    docs.sort(key=lambda d: d.get("last_activity_at", 0), reverse=True)
    return docs


def list_archived() -> list[dict]:
    docs = [d for d in _all_docs() if d.get("archived")]
    docs.sort(key=lambda d: d.get("last_activity_at", 0), reverse=True)
    return docs


def _check_file_size(size: int) -> None:
    if size > MAX_FILE_BYTES:
        raise QuotaError(
            f"Файл слишком большой (макс. {MAX_FILE_BYTES // 1024 // 1024} МБ)"
        )


def _write_version_blob(doc_id: str, number: int, content: bytes) -> None:
    blob_dir = _blob_dir(doc_id)
    blob_dir.mkdir(parents=True, exist_ok=True)
    (blob_dir / f"{number}.bin").write_bytes(content)


def create_document(
    folder_id: str | None,
    name: str,
    filename: str,
    content: bytes,
    uploaded_by: str,
    note: str = "",
    jira: str = "",
) -> dict:
    name = (name or "").strip() or Path(filename).stem or "Документ"
    if not content:
        raise ValueError("Файл пустой")
    with _lock:
        if folder_id and not any(f["id"] == folder_id for f in _read_folders()):
            raise ValueError("Папка не найдена")
        _check_file_size(len(content))
        doc_id = _new_id()
        now = time.time()
        version = {
            "number": 1,
            "uploaded_by": uploaded_by,
            "filename": Path(filename).name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "note": (note or "").strip(),
            "jira": normalize_jira(jira),
            "created_at": now,
        }
        doc = {
            "id": doc_id,
            "folder_id": folder_id or None,
            "name": name,
            "created_by": uploaded_by,
            "created_at": now,
            "last_activity_at": now,
            "archived": False,
            "versions": [version],
        }
        _write_version_blob(doc_id, 1, content)
        _write_doc(doc)
    return doc


def add_version(
    doc_id: str,
    filename: str,
    content: bytes,
    uploaded_by: str,
    note: str = "",
    jira: str = "",
    kind: str = "upload",
) -> dict:
    if not content:
        raise ValueError("Файл пустой")
    with _lock:
        doc = _read_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if doc.get("archived"):
            _unarchive(doc)  # новая версия возвращает документ в активные
        _check_file_size(len(content))
        number = (doc["versions"][-1]["number"] + 1) if doc["versions"] else 1
        now = time.time()
        version = {
            "number": number,
            "uploaded_by": uploaded_by,
            "filename": Path(filename).name,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "note": (note or "").strip(),
            "jira": normalize_jira(jira),
            "created_at": now,
            "kind": kind or "upload",
        }
        doc["versions"].append(version)
        doc["last_activity_at"] = now
        _write_version_blob(doc_id, number, content)
        _write_doc(doc)
    return doc


def version_bytes(doc_id: str, number: int) -> tuple[str, bytes]:
    """Возвращает (имя_файла, байты) запрошенной версии (в т.ч. из архива)."""
    with _lock:
        doc = _read_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        version = next((v for v in doc["versions"] if v["number"] == number), None)
        if version is None:
            raise KeyError(f"{doc_id}#{number}")
        filename = version.get("filename") or f"v{number}"
        if doc.get("archived"):
            with zipfile.ZipFile(_archive_path(doc_id)) as zf:
                return filename, zf.read(f"{number}.bin")
        return filename, (_blob_dir(doc_id) / f"{number}.bin").read_bytes()


def rename_document(doc_id: str, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажи название документа")
    with _lock:
        doc = _read_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        doc["name"] = name
        _write_doc(doc)
    return doc


def move_document(doc_id: str, folder_id: str | None) -> dict:
    folder_id = folder_id or None
    with _lock:
        doc = _read_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if folder_id is not None and not any(f["id"] == folder_id for f in _read_folders()):
            raise ValueError("Целевая папка не найдена")
        doc["folder_id"] = folder_id
        _write_doc(doc)
    return doc


def search(query: str) -> list[dict]:
    """Ищет документы по имени, заметкам версий и ссылке Jira (активные и архив)."""
    q = (query or "").strip().lower()
    if not q:
        return []
    out: list[dict] = []
    for doc in _all_docs():
        haystack = [doc.get("name", "")]
        for v in doc.get("versions", []):
            haystack.append(v.get("note", ""))
            haystack.append(v.get("jira", ""))
        if any(q in (s or "").lower() for s in haystack):
            out.append(doc)
    out.sort(key=lambda d: d.get("last_activity_at", 0), reverse=True)
    return out


def delete_document(doc_id: str) -> None:
    import shutil
    with _lock:
        try:
            path = _doc_path(doc_id)
        except ValueError:
            raise KeyError(doc_id)
        if not path.exists():
            raise KeyError(doc_id)
        path.unlink(missing_ok=True)
        blob_dir = _blob_dir(doc_id)
        if blob_dir.exists():
            shutil.rmtree(blob_dir, ignore_errors=True)


# --- архивирование ----------------------------------------------------------

def _archive(doc: dict) -> None:
    doc_id = doc["id"]
    blob_dir = _blob_dir(doc_id)
    archive = _archive_path(doc_id)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for version in doc["versions"]:
            blob = blob_dir / f"{version['number']}.bin"
            if blob.exists():
                zf.write(blob, arcname=f"{version['number']}.bin")
    for version in doc["versions"]:
        (blob_dir / f"{version['number']}.bin").unlink(missing_ok=True)
    doc["archived"] = True
    _write_doc(doc)


def _unarchive(doc: dict) -> None:
    doc_id = doc["id"]
    blob_dir = _blob_dir(doc_id)
    blob_dir.mkdir(parents=True, exist_ok=True)
    archive = _archive_path(doc_id)
    if archive.exists():
        blob_dir_resolved = blob_dir.resolve()
        with zipfile.ZipFile(archive) as zf:
            for entry in zf.namelist():
                # Защита от zip-slip: имя записи не должно вырываться из blob_dir.
                target = (blob_dir / entry).resolve()
                if not target.is_relative_to(blob_dir_resolved):
                    raise ValueError(f"Небезопасное имя записи в архиве: {entry!r}")
                target.write_bytes(zf.read(entry))
        archive.unlink(missing_ok=True)
    doc["archived"] = False
    _write_doc(doc)


def archive_document(doc_id: str) -> dict:
    with _lock:
        doc = _read_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if not doc.get("archived"):
            _archive(doc)
    return doc


def unarchive_document(doc_id: str) -> dict:
    with _lock:
        doc = _read_doc(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if doc.get("archived"):
            _unarchive(doc)
    return doc


def auto_archive_stale() -> int:
    """Архивирует документы без активности дольше ARCHIVE_AFTER_DAYS. Возвращает число."""
    if ARCHIVE_AFTER_DAYS <= 0:
        return 0
    cutoff = time.time() - ARCHIVE_AFTER_DAYS * 86400
    count = 0
    with _lock:
        for doc in _all_docs():
            if doc.get("archived") or not doc.get("versions"):
                continue
            if doc.get("last_activity_at", 0) < cutoff:
                _archive(doc)
                count += 1
    if count:
        logger.info("Авто-архив: заархивировано %d документов", count)
    return count


# --- статистика -------------------------------------------------------------

def usage() -> dict:
    docs = _all_docs()
    return {
        "max_file": MAX_FILE_BYTES,
        "doc_count": sum(1 for d in docs if not d.get("archived")),
        "archived_count": sum(1 for d in docs if d.get("archived")),
    }

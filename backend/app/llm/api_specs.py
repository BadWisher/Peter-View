"""API-связки: пара RU+EN документов OpenAPI из репозитория «Вычитка».

Раздел «Вычитка API» не хранит файлы сам – он ссылается на документы репозитория
(repo_store) по doc_id и всегда читает их ПОСЛЕДНЮЮ версию. Дифф считается между
последней и предыдущей версиями документа. Сами связки храним в data/api_specs.json.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from . import repo_store

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SPECS_FILE = DATA_DIR / "api_specs.json"

_lock = threading.RLock()


def _read() -> list[dict]:
    if not SPECS_FILE.exists():
        return []
    try:
        data = json.loads(SPECS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write(specs: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SPECS_FILE.write_text(json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_doc(doc_id: str, label: str) -> None:
    if not doc_id or repo_store.get_document(doc_id) is None:
        raise ValueError(f"Документ ({label}) не найден в репозитории")


def list_specs() -> list[dict]:
    specs = _read()
    specs.sort(key=lambda s: s.get("created_at", 0))
    return specs


def get_spec(spec_id: str) -> dict | None:
    return next((s for s in _read() if s["id"] == spec_id), None)


def create_spec(name: str, ru_doc_id: str, en_doc_id: str, created_by: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажи название связки")
    _check_doc(ru_doc_id, "RU")
    _check_doc(en_doc_id, "EN")
    with _lock:
        specs = _read()
        spec = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "ru_doc_id": ru_doc_id,
            "en_doc_id": en_doc_id,
            "created_by": created_by,
            "created_at": time.time(),
        }
        specs.append(spec)
        _write(specs)
    return spec


def update_spec(spec_id: str, name: str | None, ru_doc_id: str | None, en_doc_id: str | None) -> dict:
    with _lock:
        specs = _read()
        spec = next((s for s in specs if s["id"] == spec_id), None)
        if spec is None:
            raise KeyError(spec_id)
        if name is not None and name.strip():
            spec["name"] = name.strip()
        if ru_doc_id is not None:
            _check_doc(ru_doc_id, "RU")
            spec["ru_doc_id"] = ru_doc_id
        if en_doc_id is not None:
            _check_doc(en_doc_id, "EN")
            spec["en_doc_id"] = en_doc_id
        _write(specs)
    return spec


def delete_spec(spec_id: str) -> None:
    with _lock:
        specs = _read()
        if not any(s["id"] == spec_id for s in specs):
            raise KeyError(spec_id)
        _write([s for s in specs if s["id"] != spec_id])


def documents_for_picker() -> list[dict]:
    """Плоский список активных документов репозитория для выбора RU/EN при связывании."""
    folders = {f["id"]: f for f in repo_store.all_folders()}

    def folder_path(fid: str | None) -> str:
        parts: list[str] = []
        cur = fid
        guard = 0
        while cur and cur in folders and guard < 50:
            parts.append(folders[cur]["name"])
            cur = folders[cur].get("parent_id")
            guard += 1
        return " / ".join(reversed(parts))

    out: list[dict] = []
    for fid in [None, *folders.keys()]:
        for d in repo_store.list_documents(fid):
            out.append({
                "id": d["id"],
                "name": d["name"],
                "folder": folder_path(fid),
                "version_count": len(d.get("versions", [])),
            })
    out.sort(key=lambda x: (x["folder"], x["name"].lower()))
    return out


def doc_meta(doc_id: str) -> dict | None:
    """Краткая инфа о документе репозитория для UI (имя, число версий, последняя)."""
    doc = repo_store.get_document(doc_id)
    if doc is None:
        return None
    versions = doc.get("versions", [])
    latest = versions[-1] if versions else {}
    return {
        "id": doc_id,
        "name": doc.get("name", ""),
        "version_count": len(versions),
        "latest_number": latest.get("number"),
        "latest_at": latest.get("created_at", 0),
        "filename": latest.get("filename", ""),
    }


def latest_and_previous(doc_id: str) -> tuple[bytes, int, bytes | None, int | None]:
    """(байты последней версии, её номер, байты предыдущей|None, её номер|None).

    Здесь «предыдущая» — это просто версия на шаг назад (для скачивания/сегментов).
    Для диффа используется review-aware логика в diff_versions().
    """
    doc = repo_store.get_document(doc_id)
    if doc is None:
        raise KeyError(doc_id)
    versions = doc.get("versions", [])
    if not versions:
        raise ValueError("У документа нет версий")
    latest_num = versions[-1]["number"]
    _, latest_bytes = repo_store.version_bytes(doc_id, latest_num)
    prev_bytes = None
    prev_num = None
    if len(versions) >= 2:
        prev_num = versions[-2]["number"]
        _, prev_bytes = repo_store.version_bytes(doc_id, prev_num)
    return latest_bytes, latest_num, prev_bytes, prev_num


def _diff_baseline_index(versions: list[dict]) -> int | None:
    """Индекс версии-базы для диффа.

    База диффа не должна сдвигаться, когда поверх правок сохраняют промежуточную
    версию вычитки (kind == "review"). Логика: «текущая» ревизия – это последняя
    обычная загрузка (Ocur); база – версия прямо перед Ocur (любого типа). Так
    сохранение review-версии не ломает дифф: новой стороной становится последняя
    версия, а база остаётся прежней.
    """
    if not versions:
        return None
    ocur = None
    for i in range(len(versions) - 1, -1, -1):
        if versions[i].get("kind", "upload") != "review":
            ocur = i
            break
    if ocur is None:
        ocur = len(versions) - 1
    base = ocur - 1
    return base if base >= 0 else None


def has_diff_baseline(doc_id: str) -> bool:
    doc = repo_store.get_document(doc_id)
    if doc is None:
        return False
    return _diff_baseline_index(doc.get("versions", [])) is not None


def diff_versions(doc_id: str) -> tuple[bytes, int, bytes | None, int | None]:
    """(новая сторона = последняя версия, её номер, база|None, её номер|None).

    Review-aware: промежуточные сохранения вычитки не сдвигают базу диффа.
    """
    doc = repo_store.get_document(doc_id)
    if doc is None:
        raise KeyError(doc_id)
    versions = doc.get("versions", [])
    if not versions:
        raise ValueError("У документа нет версий")
    new_num = versions[-1]["number"]
    _, new_bytes = repo_store.version_bytes(doc_id, new_num)
    base_idx = _diff_baseline_index(versions)
    if base_idx is None:
        return new_bytes, new_num, None, None
    base_num = versions[base_idx]["number"]
    _, base_bytes = repo_store.version_bytes(doc_id, base_num)
    return new_bytes, new_num, base_bytes, base_num

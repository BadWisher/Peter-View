"""Очередь задач извлечения правил из docx с персистентностью в SQLite.

Извлечение может быть долгим (несколько LLM-вызовов), поэтому крутится в фоне,
а фронт опрашивает статус. Статус и результат пишутся в SQLite (переживают
рестарт), исходный файл сохраняется на диск рядом с базой: он нужен для кнопки
«Обновить стайл гайд» после перезапуска контейнера.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .documents import Document
from .extractor import extract_rules

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 60 * 60 * 24
EXTRACT_TIMEOUT_SECONDS = float(os.getenv("STYLEGUIDE_EXTRACT_TIMEOUT", "900"))

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_FILE = DATA_DIR / "extract_jobs.db"
UPLOAD_DIR = DATA_DIR / "uploads"

_db_lock = threading.Lock()
_jobs: dict[str, "ExtractJob"] = {}
_tasks: set[asyncio.Task] = set()


@dataclass
class ExtractJob:
    id: str
    source_filename: str
    status: str = "pending"
    stage: str = "В очереди"
    rules: list[dict] | None = None
    lexicon: dict | None = None
    error: str | None = None
    warning: str | None = None
    diagnostics: dict | None = None
    created_at: float = field(default_factory=time.time)


def _connect() -> sqlite3.Connection:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _db_lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extract_jobs (
                id TEXT PRIMARY KEY,
                source_filename TEXT,
                status TEXT,
                stage TEXT,
                rules TEXT,
                lexicon TEXT,
                error TEXT,
                warning TEXT,
                diagnostics TEXT,
                created_at REAL
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(extract_jobs)")}
        if "lexicon" not in columns:
            conn.execute("ALTER TABLE extract_jobs ADD COLUMN lexicon TEXT")
        conn.execute(
            """
            UPDATE extract_jobs SET status='error', error=?
            WHERE status IN ('pending','running')
            """,
            ("Прервано рестартом сервера, загрузите документ заново",),
        )
        conn.commit()


def _persist(job: ExtractJob) -> None:
    try:
        with _db_lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO extract_jobs (
                    id, source_filename, status, stage, rules, lexicon,
                    error, warning, diagnostics, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    stage=excluded.stage,
                    rules=excluded.rules,
                    lexicon=excluded.lexicon,
                    error=excluded.error,
                    warning=excluded.warning,
                    diagnostics=excluded.diagnostics
                """,
                (
                    job.id,
                    job.source_filename,
                    job.status,
                    job.stage,
                    json.dumps(job.rules, ensure_ascii=False) if job.rules is not None else None,
                    json.dumps(job.lexicon, ensure_ascii=False) if job.lexicon is not None else None,
                    job.error,
                    job.warning,
                    json.dumps(job.diagnostics, ensure_ascii=False) if job.diagnostics else None,
                    job.created_at,
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось сохранить задачу извлечения %s: %s", job.id, e)


def _load(job_id: str) -> ExtractJob | None:
    try:
        with _db_lock, _connect() as conn:
            row = conn.execute(
                "SELECT * FROM extract_jobs WHERE id=?", (job_id,)
            ).fetchone()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать задачу извлечения %s: %s", job_id, e)
        return None
    if row is None:
        return None
    keys = row.keys()
    lexicon_raw = row["lexicon"] if "lexicon" in keys else None
    return ExtractJob(
        id=row["id"],
        source_filename=row["source_filename"] or "",
        status=row["status"] or "error",
        stage=row["stage"] or "",
        rules=json.loads(row["rules"]) if row["rules"] else None,
        lexicon=json.loads(lexicon_raw) if lexicon_raw else None,
        error=row["error"],
        warning=row["warning"],
        diagnostics=json.loads(row["diagnostics"]) if row["diagnostics"] else None,
        created_at=row["created_at"] or time.time(),
    )


def _cleanup() -> None:
    now = time.time()
    stale = [jid for jid, job in _jobs.items() if now - job.created_at > JOB_TTL_SECONDS]
    for jid in stale:
        _jobs.pop(jid, None)
    try:
        with _db_lock, _connect() as conn:
            rows = conn.execute(
                "SELECT id FROM extract_jobs WHERE ? - created_at > ?",
                (now, JOB_TTL_SECONDS),
            ).fetchall()
            if not rows:
                return
            conn.executemany(
                "DELETE FROM extract_jobs WHERE id=?",
                [(row["id"],) for row in rows],
            )
            for row in rows:
                _remove_upload(row["id"])
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось почистить старые задачи извлечения: %s", e)


def save_upload(job_id: str, filename: str, content: bytes) -> None:
    """Сохраняет исходный файл на volume: имя без пути, содержимое как есть."""
    safe_name = Path(filename).name or f"{job_id}.docx"
    suffix = Path(safe_name).suffix or ".docx"
    try:
        path = UPLOAD_DIR / f"{job_id}{suffix}"
        path.write_bytes(content)
    except OSError as e:
        logger.warning("Не удалось сохранить исходник задачи %s: %s", job_id, e)


def get_upload_path(job_id: str) -> Path | None:
    for candidate in sorted(UPLOAD_DIR.glob(f"{job_id}.*")):
        return candidate
    return None


def _remove_upload(job_id: str) -> None:
    for path in UPLOAD_DIR.glob(f"{job_id}.*"):
        try:
            path.unlink()
        except OSError:
            pass


def get_job(job_id: str) -> ExtractJob | None:
    """Живой объект из памяти, иначе восстановленный из SQLite."""
    job = _jobs.get(job_id)
    if job is not None:
        return job
    return _load(job_id)


def submit(document: Document, source_filename: str, content: bytes | None = None) -> str:
    _cleanup()
    job = ExtractJob(id=uuid.uuid4().hex, source_filename=source_filename)
    _jobs[job.id] = job
    _persist(job)
    if content:
        save_upload(job.id, source_filename, content)
    task = asyncio.create_task(_run(job, document))
    # Держим ссылку на таск, иначе сборщик мусора может прибить его на середине.
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job.id


async def _run(job: ExtractJob, document: Document) -> None:
    job.status = "running"

    def progress(stage: str) -> None:
        job.stage = stage

    try:
        result = await asyncio.wait_for(
            extract_rules(document, progress),
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
        if not result.rules:
            raise RuntimeError("Не удалось извлечь ни одного правила из документа")
        job.rules = result.rules
        job.lexicon = result.lexicon or {"forbidden": [], "allowed": []}
        job.diagnostics = {
            "chunks_total": result.chunks_total,
            "chunks_succeeded": result.chunks_succeeded,
            "chunks_failed": result.chunks_failed,
            "chunks_empty": result.chunks_empty,
            "rules_extracted": len(result.rules),
            "lexicon_forbidden": len((result.lexicon or {}).get("forbidden") or []),
            "lexicon_allowed": len((result.lexicon or {}).get("allowed") or []),
        }
        if result.partial:
            job.warning = (
                f"Извлечение частичное: не обработано фрагментов "
                f"{result.chunks_failed} из {result.chunks_total}. "
                "Повтори загрузку или проверь журнал backend."
            )
        job.status = "done"
        job.stage = "Готово с предупреждением" if job.warning else "Готово"
    except asyncio.TimeoutError:
        job.status = "error"
        job.error = f"Превышен таймаут извлечения ({EXTRACT_TIMEOUT_SECONDS:.0f}с)"
    except Exception as e:  # noqa: BLE001
        logger.exception("Извлечение правил %s завершилось с ошибкой", job.id)
        job.status = "error"
        job.error = str(e)
    finally:
        _persist(job)


_init_db()

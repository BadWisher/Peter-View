"""Очередь задач LLM-вычитки с персистентностью в SQLite.

Сам прогон крутится в фоне на asyncio (живой объект Job — в памяти), но его статус,
стадия и готовый отчёт пишутся в SQLite. Это переживает рестарт контейнера: готовые
отчёты остаются доступны, а задачи, прерванные рестартом, помечаются ошибкой.
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
from typing import Any, Awaitable, Callable

from . import stats
from .documents import Document
from .pipeline import run_pipeline
from .styleguide import StyleGuide

logger = logging.getLogger(__name__)

JOB_TTL_SECONDS = 60 * 60
JOB_TIMEOUT_SECONDS = float(os.getenv("LLM_JOB_TIMEOUT", "900"))
# Максимум символов в одном потоке вывода воркера (обрезаем с начала).
STREAM_BLOCK_CAP = int(os.getenv("LLM_STREAM_BLOCK_CAP", "20000"))

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_FILE = DATA_DIR / "jobs.db"

_db_lock = threading.Lock()
_jobs: dict[str, "Job"] = {}


@dataclass
class Job:
    id: str
    source: str
    user: str = ""
    status: str = "pending"
    stage: str = "В очереди"
    report: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    # Живой стриминг вывода воркеров (только в памяти, отдаётся через SSE).
    # stream_order — порядок появления проходов; stream_blocks — id -> блок.
    stream_order: list[int] = field(default_factory=list)
    stream_blocks: dict[int, dict[str, Any]] = field(default_factory=dict)
    stream_wakeup: asyncio.Event | None = field(default=None, repr=False, compare=False)


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _db_lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source TEXT,
                status TEXT,
                stage TEXT,
                report TEXT,
                error TEXT,
                created_at REAL
            )
            """
        )
        # Задачи, не доведённые до конца в прошлом процессе, после рестарта зависли бы
        # навсегда — помечаем их ошибкой.
        conn.execute(
            "UPDATE jobs SET status='error', error=? WHERE status IN ('pending','running')",
            ("Прервано рестартом сервера, запустите проверку заново",),
        )
        conn.commit()


def _persist(job: Job) -> None:
    report_json = json.dumps(job.report, ensure_ascii=False) if job.report is not None else None
    try:
        with _db_lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, source, status, stage, report, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    stage=excluded.stage,
                    report=excluded.report,
                    error=excluded.error
                """,
                (job.id, job.source, job.status, job.stage, report_json, job.error, job.created_at),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось сохранить задачу %s в SQLite: %s", job.id, e)


def _load(job_id: str) -> Job | None:
    try:
        with _db_lock, _connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать задачу %s из SQLite: %s", job_id, e)
        return None
    if row is None:
        return None
    return Job(
        id=row["id"],
        source=row["source"] or "",
        status=row["status"] or "error",
        stage=row["stage"] or "",
        report=json.loads(row["report"]) if row["report"] else None,
        error=row["error"],
        created_at=row["created_at"] or time.time(),
    )


def _cleanup() -> None:
    now = time.time()
    stale = [jid for jid, job in _jobs.items() if now - job.created_at > JOB_TTL_SECONDS]
    for jid in stale:
        _jobs.pop(jid, None)
    try:
        with _db_lock, _connect() as conn:
            conn.execute("DELETE FROM jobs WHERE ? - created_at > ?", (now, JOB_TTL_SECONDS))
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось почистить старые задачи: %s", e)


def get_job(job_id: str) -> Job | None:
    """Живой объект из памяти, иначе — восстановленный из SQLite (переживает рестарт)."""
    job = _jobs.get(job_id)
    if job is not None:
        return job
    return _load(job_id)


def submit(document: Document, guide: StyleGuide, user: str = "", options: dict | None = None) -> str:
    _cleanup()
    job = Job(id=uuid.uuid4().hex, source=document.source, user=user)
    _jobs[job.id] = job
    _persist(job)
    asyncio.create_task(_run(job, document, guide, options=options))
    return job.id


def submit_task(
    source: str,
    runner: Callable[[Callable[[str], None]], Awaitable[dict[str, Any]]],
    user: str = "",
) -> str:
    """Универсальная задача: runner(progress) -> готовый report-словарь.

    Переиспользует персистентность, статус-поллинг, отчёт и привязку токенов к
    пользователю. Применяется для вычитки и перевода диффа API.
    """
    _cleanup()
    job = Job(id=uuid.uuid4().hex, source=source, user=user)
    _jobs[job.id] = job
    _persist(job)
    asyncio.create_task(_run_task(job, runner))
    return job.id


async def _run_task(
    job: Job,
    runner: Callable[[Callable[[str], None]], Awaitable[dict[str, Any]]],
) -> None:
    stats.set_context(job.user, job.id)
    job.status = "running"
    _persist(job)

    def progress(stage: str) -> None:
        job.stage = stage
        _persist(job)

    try:
        report = await asyncio.wait_for(runner(progress), timeout=JOB_TIMEOUT_SECONDS)
        report.setdefault("meta", {})["token_usage"] = stats.job_token_usage(job.id)
        report["job_id"] = job.id
        job.report = report
        job.status = "done"
        job.stage = "Готово"
    except asyncio.TimeoutError:
        logger.warning("Задача %s превысила таймаут %.0fс", job.id, JOB_TIMEOUT_SECONDS)
        job.status = "error"
        job.error = f"Превышен таймаут ({JOB_TIMEOUT_SECONDS:.0f}с)"
    except Exception as e:  # noqa: BLE001
        logger.exception("Задача %s завершилась с ошибкой", job.id)
        job.status = "error"
        job.error = str(e)
    finally:
        _persist(job)


async def _run(job: Job, document: Document, guide: StyleGuide, options: dict | None = None) -> None:
    # Привязываем токены LLM этого прогона к пользователю и задаче.
    stats.set_context(job.user, job.id)
    job.status = "running"
    _persist(job)

    def progress(stage: str) -> None:
        job.stage = stage
        _persist(job)

    job.stream_wakeup = asyncio.Event()

    def stream(ev: dict) -> None:
        # Состояние живёт только в памяти; SSE-эндпоинт читает его и шлёт дельты.
        t = ev.get("type")
        if t == "start":
            pid = ev["id"]
            job.stream_order.append(pid)
            job.stream_blocks[pid] = {
                "id": pid, "worker": ev.get("worker", ""), "scope": ev.get("scope", ""),
                "text": "", "status": "running",
            }
        elif t == "delta":
            b = job.stream_blocks.get(ev["id"])
            if b is not None:
                b["text"] += ev.get("text", "")
                if len(b["text"]) > STREAM_BLOCK_CAP:
                    b["text"] = b["text"][-STREAM_BLOCK_CAP:]
        elif t == "end":
            b = job.stream_blocks.get(ev["id"])
            if b is not None:
                b["status"] = ev.get("status", "done")
                if "found" in ev:
                    b["found"] = ev.get("found")
                if ev.get("error"):
                    b["error"] = ev["error"]
        wakeup = job.stream_wakeup
        if wakeup is not None and not wakeup.is_set():
            wakeup.set()

    try:
        report = await asyncio.wait_for(
            run_pipeline(document, guide, progress, stream, options=options),
            timeout=JOB_TIMEOUT_SECONDS,
        )
        report.setdefault("meta", {})["token_usage"] = stats.job_token_usage(job.id)
        report["job_id"] = job.id
        job.report = report
        job.status = "done"
        job.stage = "Готово"
        if job.user:
            issues = report.get("issues", []) or []
            stats.add_rule_hits(job.user, issues)
            stats.add_history(job.user, report)
    except asyncio.TimeoutError:
        logger.warning("Задача %s превысила таймаут %.0fс", job.id, JOB_TIMEOUT_SECONDS)
        job.status = "error"
        job.error = f"Превышен таймаут проверки ({JOB_TIMEOUT_SECONDS:.0f}с)"
    except Exception as e:  # noqa: BLE001
        logger.exception("Задача %s завершилась с ошибкой", job.id)
        job.status = "error"
        job.error = str(e)
    finally:
        wakeup = job.stream_wakeup
        if wakeup is not None:
            wakeup.set()
        _persist(job)


_init_db()

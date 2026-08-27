"""Персистентная статистика и кэш в одном SQLite (data/stats.db).

Хранит:
- token_usage   — токены LLM (вход/выход) с привязкой к пользователю и задаче;
- rule_hits     — сколько раз у пользователя срабатывало каждое правило (для пасхалки);
- check_history — история проверок с полным отчётом (можно открыть заново);
- doc_views     — когда пользователь последний раз открывал документ репозитория;
- llm_cache     — кэш ответов модели по содержимому запроса (переживает рестарт).

Текущий пользователь/задача берутся из contextvars: их выставляет jobs._run, а
client.complete_json дёргает record_tokens, не зная деталей вызова.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_FILE = DATA_DIR / "stats.db"
HISTORY_KEEP = 50

_lock = threading.Lock()

_ctx_user: contextvars.ContextVar[str] = contextvars.ContextVar("stats_user", default="")
_ctx_job: contextvars.ContextVar[str] = contextvars.ContextVar("stats_job", default="")
_ctx_worker: contextvars.ContextVar[str] = contextvars.ContextVar("stats_worker", default="")


def set_context(user: str, job_id: str) -> None:
    _ctx_user.set(user or "")
    _ctx_job.set(job_id or "")


def set_worker(worker: str):
    return _ctx_worker.set(worker or "")


def reset_worker(token) -> None:
    _ctx_worker.reset(token)


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL, user TEXT, job_id TEXT,
                prompt_tokens INTEGER, completion_tokens INTEGER,
                cached_tokens INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_token_ts ON token_usage(ts);

            CREATE TABLE IF NOT EXISTS rule_hits (
                user TEXT, rule_id TEXT, description TEXT,
                count INTEGER, last_ts REAL,
                PRIMARY KEY (user, rule_id)
            );

            CREATE TABLE IF NOT EXISTS check_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT, ts REAL, source TEXT,
                styleguide_id TEXT, styleguide_name TEXT,
                total INTEGER, errors INTEGER, warnings INTEGER, suggestions INTEGER,
                report TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_history_user ON check_history(user, ts);

            CREATE TABLE IF NOT EXISTS doc_views (
                user TEXT, doc_id TEXT, ts REAL,
                PRIMARY KEY (user, doc_id)
            );

            CREATE TABLE IF NOT EXISTS llm_cache (
                key TEXT PRIMARY KEY, response TEXT, ts REAL
            );
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(token_usage)").fetchall()
        }
        if "worker" not in columns:
            conn.execute("ALTER TABLE token_usage ADD COLUMN worker TEXT DEFAULT ''")
        if "cached_tokens" not in columns:
            conn.execute(
                "ALTER TABLE token_usage ADD COLUMN cached_tokens INTEGER DEFAULT 0"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_job ON token_usage(job_id, worker)"
        )
        conn.commit()


# --- токены -----------------------------------------------------------------

def record_tokens(
    prompt_tokens: int, completion_tokens: int, cached_tokens: int | None = None,
) -> None:
    if not prompt_tokens and not completion_tokens:
        return
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO token_usage "
                "(ts, user, job_id, worker, prompt_tokens, completion_tokens, cached_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), _ctx_user.get(), _ctx_job.get(),
                 _ctx_worker.get(), int(prompt_tokens or 0), int(completion_tokens or 0),
                 int(cached_tokens or 0)),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось записать токены: %s", e)


def token_totals() -> dict:
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    try:
        with _lock, _connect() as conn:
            total = conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(completion_tokens),0) c, "
                "COUNT(*) n FROM token_usage"
            ).fetchone()
            today = conn.execute(
                "SELECT COALESCE(SUM(prompt_tokens),0) p, COALESCE(SUM(completion_tokens),0) c, "
                "COUNT(*) n FROM token_usage WHERE ts >= ?",
                (midnight,),
            ).fetchone()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать токены: %s", e)
        return {"total": {}, "today": {}}
    return {
        "total": {"prompt": total["p"], "completion": total["c"],
                  "tokens": total["p"] + total["c"], "calls": total["n"]},
        "today": {"prompt": today["p"], "completion": today["c"],
                  "tokens": today["p"] + today["c"], "calls": today["n"]},
    }


def job_token_usage(job_id: str) -> dict:
    if not job_id:
        return {"prompt": 0, "completion": 0, "tokens": 0, "calls": 0,
                "cached_prompt": 0, "by_worker": {}}
    try:
        with _lock, _connect() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(worker, '') worker,
                       COALESCE(SUM(prompt_tokens), 0) prompt,
                       COALESCE(SUM(completion_tokens), 0) completion,
                       COALESCE(SUM(cached_tokens), 0) cached,
                       COUNT(*) calls
                FROM token_usage WHERE job_id=? GROUP BY COALESCE(worker, '')
                """,
                (job_id,),
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать токены задачи: %s", e)
        return {"prompt": 0, "completion": 0, "tokens": 0, "calls": 0,
                "cached_prompt": 0, "by_worker": {}}
    by_worker = {
        (row["worker"] or "unknown"): {
            "prompt": row["prompt"],
            "completion": row["completion"],
            "tokens": row["prompt"] + row["completion"],
            "calls": row["calls"],
            "cached_prompt": row["cached"],
        }
        for row in rows
    }
    return {
        "prompt": sum(value["prompt"] for value in by_worker.values()),
        "completion": sum(value["completion"] for value in by_worker.values()),
        "tokens": sum(value["tokens"] for value in by_worker.values()),
        "calls": sum(value["calls"] for value in by_worker.values()),
        "cached_prompt": sum(value["cached_prompt"] for value in by_worker.values()),
        "by_worker": by_worker,
    }


# --- частые ошибки ----------------------------------------------------------

def add_rule_hits(user: str, issues: list[dict]) -> None:
    """Накапливает счётчики правил по замечаниям отчёта (UI-формат: rule, message)."""
    if not user or not issues:
        return
    now = time.time()
    try:
        with _lock, _connect() as conn:
            for issue in issues:
                rule_id = (issue.get("rule") or "").strip()
                if not rule_id:
                    continue
                desc = (issue.get("message") or "").split("\n", 1)[0][:160]
                conn.execute(
                    """
                    INSERT INTO rule_hits (user, rule_id, description, count, last_ts)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(user, rule_id) DO UPDATE SET
                        count = count + 1,
                        description = excluded.description,
                        last_ts = excluded.last_ts
                    """,
                    (user, rule_id, desc, now),
                )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось записать rule_hits: %s", e)


def top_rules_by_user(limit_per_user: int = 15) -> dict:
    """Топ нарушаемых правил отдельно по каждому пользователю (видит каждый)."""
    try:
        with _lock, _connect() as conn:
            rows = conn.execute(
                "SELECT user, rule_id, description, count, last_ts FROM rule_hits "
                "ORDER BY count DESC, last_ts DESC"
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать rule_hits: %s", e)
        return {"users": []}

    by_user: dict[str, dict] = {}
    for r in rows:
        u = r["user"] or "–"
        bucket = by_user.setdefault(
            u, {"user": u, "total_hits": 0, "distinct_rules": 0, "rules": []}
        )
        bucket["total_hits"] += r["count"]
        bucket["distinct_rules"] += 1
        if len(bucket["rules"]) < limit_per_user:
            bucket["rules"].append({
                "rule_id": r["rule_id"], "description": r["description"],
                "count": r["count"], "last_ts": r["last_ts"],
            })
    users = sorted(by_user.values(), key=lambda b: b["total_hits"], reverse=True)
    return {"users": users}


# --- история проверок -------------------------------------------------------

def add_history(user: str, report: dict) -> None:
    if not user or not isinstance(report, dict):
        return
    summary = report.get("summary", {}) or {}
    sg = report.get("styleguide", {}) or {}
    try:
        with _lock, _connect() as conn:
            conn.execute(
                """
                INSERT INTO check_history
                    (user, ts, source, styleguide_id, styleguide_name,
                     total, errors, warnings, suggestions, report)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user, time.time(), report.get("document", ""),
                    sg.get("id", ""), sg.get("name", ""),
                    int(summary.get("total", 0)), int(summary.get("errors", 0)),
                    int(summary.get("warnings", 0)), int(summary.get("suggestions", 0)),
                    json.dumps(report, ensure_ascii=False),
                ),
            )
            # держим только последние HISTORY_KEEP записей на пользователя
            conn.execute(
                """
                DELETE FROM check_history
                WHERE user = ? AND id NOT IN (
                    SELECT id FROM check_history WHERE user = ?
                    ORDER BY ts DESC LIMIT ?
                )
                """,
                (user, user, HISTORY_KEEP),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось записать историю: %s", e)


def recent_history(user: str, limit: int = 30, offset: int = 0) -> list[dict]:
    try:
        with _lock, _connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, source, styleguide_name, total, errors, warnings, suggestions "
                "FROM check_history WHERE user = ? ORDER BY ts DESC LIMIT ? OFFSET ?",
                (user, limit, offset),
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать историю: %s", e)
        return []
    return [dict(r) for r in rows]


def history_count(user: str) -> int:
    try:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c FROM check_history WHERE user = ?", (user,)
            ).fetchone()
            return int(row["c"]) if row else 0
    except sqlite3.Error as e:
        logger.warning("Не удалось посчитать историю: %s", e)
        return 0


def history_report(user: str, history_id: int) -> dict | None:
    try:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT report FROM check_history WHERE id = ? AND user = ?",
                (history_id, user),
            ).fetchone()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать отчёт истории: %s", e)
        return None
    if row is None or not row["report"]:
        return None
    try:
        return json.loads(row["report"])
    except json.JSONDecodeError:
        return None


# --- просмотры документов ---------------------------------------------------

def mark_seen(user: str, doc_id: str) -> None:
    if not user or not doc_id:
        return
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO doc_views (user, doc_id, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(user, doc_id) DO UPDATE SET ts = excluded.ts",
                (user, doc_id, time.time()),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось отметить просмотр: %s", e)


def last_views(user: str) -> dict[str, float]:
    if not user:
        return {}
    try:
        with _lock, _connect() as conn:
            rows = conn.execute(
                "SELECT doc_id, ts FROM doc_views WHERE user = ?", (user,)
            ).fetchall()
    except sqlite3.Error as e:
        logger.warning("Не удалось прочитать просмотры: %s", e)
        return {}
    return {r["doc_id"]: r["ts"] for r in rows}


# --- кэш ответов LLM --------------------------------------------------------

def cache_get(key: str) -> dict | None:
    try:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE key = ?", (key,)
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        return json.loads(row["response"])
    except json.JSONDecodeError:
        return None


def cache_set(key: str, response: dict) -> None:
    try:
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO llm_cache (key, response, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET response = excluded.response, ts = excluded.ts",
                (key, json.dumps(response, ensure_ascii=False), time.time()),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("Не удалось сохранить кэш LLM: %s", e)


_init_db()

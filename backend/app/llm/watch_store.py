"""Хранилище групп URL для внешнего наблюдения.

Группы общие для всех пользователей: один клиентский портал смотрит вся команда.
Пароли лежат только в зашифрованном виде и наружу не отдаются.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_FILE = Path(os.getenv("WATCH_STORE_PATH", str(DATA_DIR / "watch.db")))
SNAPSHOT_KEEP = int(os.getenv("WATCH_SNAPSHOT_KEEP", "14"))
TEXT_CAP = int(os.getenv("WATCH_TEXT_CAP", "200000"))
AUTH_KINDS = frozenset({"none", "basic", "form"})

_lock = threading.Lock()
_SECRET = os.getenv("PROOFREADER_SECRET", "proofreader-local-watch").encode("utf-8")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                auth_kind TEXT NOT NULL DEFAULT 'none',
                login_url TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                password_enc TEXT NOT NULL DEFAULT '',
                username_field TEXT NOT NULL DEFAULT 'username',
                password_field TEXT NOT NULL DEFAULT 'password',
                created_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                last_run_at REAL
            );
            CREATE TABLE IF NOT EXISTS pages (
                id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_status TEXT NOT NULL DEFAULT 'pending',
                last_checked_at REAL,
                last_changed_at REAL,
                last_error TEXT,
                content_hash TEXT,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id TEXT NOT NULL,
                checked_at REAL NOT NULL,
                content_hash TEXT NOT NULL,
                text TEXT NOT NULL,
                changed INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.commit()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def encrypt_secret(plain: str) -> str:
    raw = (plain or "").encode("utf-8")
    if not raw:
        return ""
    nonce = os.urandom(16)
    key = hashlib.sha256(_SECRET + nonce).digest()
    stream = (key * ((len(raw) // len(key)) + 1))[: len(raw)]
    xored = bytes(a ^ b for a, b in zip(raw, stream))
    mac = hmac.new(_SECRET, nonce + xored, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + mac + xored).decode("ascii")


def decrypt_secret(blob: str) -> str:
    if not blob:
        return ""
    try:
        data = base64.urlsafe_b64decode(blob.encode("ascii"))
        nonce, mac, xored = data[:16], data[16:32], data[32:]
        expected = hmac.new(_SECRET, nonce + xored, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(mac, expected):
            return ""
        key = hashlib.sha256(_SECRET + nonce).digest()
        stream = (key * ((len(xored) // len(key)) + 1))[: len(xored)]
        return bytes(a ^ b for a, b in zip(xored, stream)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _validate_url(url: str) -> str:
    value = (url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("URL должен начинаться с http:// или https://")
    return value


def _row_group(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "auth_kind": row["auth_kind"],
        "login_url": row["login_url"],
        "username": row["username"],
        "has_password": bool(row["password_enc"]),
        "username_field": row["username_field"],
        "password_field": row["password_field"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "last_run_at": row["last_run_at"],
    }


def _row_page(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "url": row["url"],
        "title": row["title"],
        "enabled": bool(row["enabled"]),
        "last_status": row["last_status"],
        "last_checked_at": row["last_checked_at"],
        "last_changed_at": row["last_changed_at"],
        "last_error": row["last_error"],
        "content_hash": row["content_hash"],
    }


def list_groups() -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT g.*,
                   (SELECT COUNT(*) FROM pages p WHERE p.group_id = g.id) AS page_count,
                   (SELECT COUNT(*) FROM pages p WHERE p.group_id = g.id AND p.last_status = 'changed') AS changed_count,
                   (SELECT COUNT(*) FROM pages p WHERE p.group_id = g.id AND p.last_status = 'error') AS error_count
            FROM groups g
            ORDER BY g.name COLLATE NOCASE
            """
        ).fetchall()
    result = []
    for row in rows:
        item = _row_group(row)
        item["page_count"] = int(row["page_count"] or 0)
        item["changed_count"] = int(row["changed_count"] or 0)
        item["error_count"] = int(row["error_count"] or 0)
        result.append(item)
    return result


def get_group(group_id: str, *, with_secret: bool = False) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        return None
    data = _row_group(row)
    if with_secret:
        data["password"] = decrypt_secret(row["password_enc"])
    return data


def create_group(
    name: str,
    *,
    auth_kind: str = "none",
    login_url: str = "",
    username: str = "",
    password: str = "",
    username_field: str = "username",
    password_field: str = "password",
    created_by: str = "",
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажи название группы")
    kind = (auth_kind or "none").strip()
    if kind not in AUTH_KINDS:
        raise ValueError("Неизвестный способ входа")
    login = _validate_url(login_url) if kind == "form" else ""
    group_id = _new_id()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO groups (
                id, name, auth_kind, login_url, username, password_enc,
                username_field, password_field, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id,
                name,
                kind,
                login if kind == "form" else "",
                (username or "").strip(),
                encrypt_secret(password),
                (username_field or "username").strip() or "username",
                (password_field or "password").strip() or "password",
                created_by,
                now,
            ),
        )
        conn.commit()
    return get_group(group_id)  # type: ignore[return-value]


def update_group(group_id: str, **fields: Any) -> dict[str, Any]:
    current = get_group(group_id)
    if current is None:
        raise KeyError("Группа не найдена")
    name = (fields.get("name", current["name"]) or "").strip()
    if not name:
        raise ValueError("Укажи название группы")
    kind = (fields.get("auth_kind", current["auth_kind"]) or "none").strip()
    if kind not in AUTH_KINDS:
        raise ValueError("Неизвестный способ входа")
    login_url = fields.get("login_url", current["login_url"]) or ""
    login_url = login_url.strip()
    if kind == "form":
        login_url = _validate_url(login_url)
    else:
        login_url = ""
    username = (fields.get("username", current["username"]) or "").strip()
    username_field = (fields.get("username_field", current["username_field"]) or "username").strip() or "username"
    password_field = (fields.get("password_field", current["password_field"]) or "password").strip() or "password"
    password = fields.get("password")
    with _lock, _connect() as conn:
        if password is None or str(password) == "":
            conn.execute(
                """
                UPDATE groups SET name=?, auth_kind=?, login_url=?, username=?,
                    username_field=?, password_field=?
                WHERE id=?
                """,
                (name, kind, login_url, username, username_field, password_field, group_id),
            )
        else:
            conn.execute(
                """
                UPDATE groups SET name=?, auth_kind=?, login_url=?, username=?,
                    password_enc=?, username_field=?, password_field=?
                WHERE id=?
                """,
                (
                    name, kind, login_url, username, encrypt_secret(str(password)),
                    username_field, password_field, group_id,
                ),
            )
        conn.commit()
    return get_group(group_id)  # type: ignore[return-value]


def delete_group(group_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        conn.commit()


def list_pages(group_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pages WHERE group_id = ? ORDER BY title COLLATE NOCASE, url",
            (group_id,),
        ).fetchall()
    return [_row_page(row) for row in rows]


def get_page(page_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,)).fetchone()
    return _row_page(row) if row else None


def add_page(group_id: str, url: str, title: str = "") -> dict[str, Any]:
    if get_group(group_id) is None:
        raise KeyError("Группа не найдена")
    url = _validate_url(url)
    title = (title or "").strip() or urlparse(url).path.rstrip("/") or url
    page_id = _new_id()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO pages (id, group_id, url, title, enabled, last_status)
            VALUES (?, ?, ?, ?, 1, 'pending')
            """,
            (page_id, group_id, url, title),
        )
        conn.commit()
    return get_page(page_id)  # type: ignore[return-value]


def update_page(page_id: str, **fields: Any) -> dict[str, Any]:
    current = get_page(page_id)
    if current is None:
        raise KeyError("Адрес не найден")
    url = _validate_url(fields["url"]) if "url" in fields else current["url"]
    title = (fields.get("title", current["title"]) or "").strip() or url
    enabled = current["enabled"] if "enabled" not in fields else bool(fields["enabled"])
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE pages SET url=?, title=?, enabled=? WHERE id=?",
            (url, title, 1 if enabled else 0, page_id),
        )
        conn.commit()
    return get_page(page_id)  # type: ignore[return-value]


def delete_page(page_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))
        conn.commit()


def record_snapshot(
    page_id: str,
    *,
    text: str,
    content_hash: str,
    changed: bool,
    error: str | None = None,
) -> None:
    now = time.time()
    clipped = text[:TEXT_CAP]
    status = "error" if error else ("changed" if changed else "same")
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (page_id, checked_at, content_hash, text, changed, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (page_id, now, content_hash, clipped, 1 if changed else 0, error),
        )
        conn.execute(
            """
            UPDATE pages SET last_status=?, last_checked_at=?, last_error=?, content_hash=?,
                last_changed_at = CASE WHEN ? THEN ? ELSE last_changed_at END
            WHERE id=?
            """,
            (status, now, error, content_hash, 1 if changed else 0, now, page_id),
        )
        extra = conn.execute(
            """
            SELECT id FROM snapshots WHERE page_id = ? ORDER BY checked_at DESC
            """,
            (page_id,),
        ).fetchall()
        drop_ids = [row["id"] for row in extra[SNAPSHOT_KEEP:]]
        if drop_ids:
            conn.execute(
                f"DELETE FROM snapshots WHERE id IN ({','.join('?' * len(drop_ids))})",
                drop_ids,
            )
        conn.commit()


def mark_group_run(group_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("UPDATE groups SET last_run_at = ? WHERE id = ?", (time.time(), group_id))
        conn.commit()


def latest_snapshots(page_id: str, limit: int = 2) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, checked_at, content_hash, text, changed, error
            FROM snapshots WHERE page_id = ?
            ORDER BY checked_at DESC LIMIT ?
            """,
            (page_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def list_snapshots(page_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, checked_at, content_hash, changed, error,
                   length(text) AS text_length
            FROM snapshots WHERE page_id = ?
            ORDER BY checked_at DESC LIMIT ?
            """,
            (page_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_daily_stamp() -> str:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'last_daily'").fetchone()
    return row["value"] if row else ""


def set_daily_stamp(value: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('last_daily', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (value,),
        )
        conn.commit()


_init_db()

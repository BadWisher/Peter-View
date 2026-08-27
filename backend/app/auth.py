from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import bcrypt
from fastapi import HTTPException, Request

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
SESSION_COOKIE = "proofreader_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
COOKIE_SECURE = os.getenv("PROOFREADER_COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
MIN_PASSWORD = 8
ROLES = ("admin", "editor")

SESSIONS: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
logger = logging.getLogger(__name__)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def check_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _normalize_entry(username: str, value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {
            "password": value,
            "role": "admin" if username == "admin" else "editor",
            "source": "local",
        }
    if not isinstance(value, dict):
        return {"password": "", "role": "editor", "source": "local"}
    role = value.get("role") if value.get("role") in ROLES else "editor"
    return {
        "password": str(value.get("password") or ""),
        "role": role,
        "source": value.get("source") or "local",
        "oidc_sub": value.get("oidc_sub") or "",
    }


def read_users() -> dict[str, dict[str, Any]]:
    with _lock:
        if not USERS_FILE.exists():
            return {}
        try:
            data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {name: _normalize_entry(name, val) for name, val in data.items()}


def write_users(users: dict[str, dict[str, Any]]) -> None:
    payload = {
        name: {
            "password": rec.get("password") or "",
            "role": rec.get("role") if rec.get("role") in ROLES else "editor",
            "source": rec.get("source") or "local",
            **({"oidc_sub": rec["oidc_sub"]} if rec.get("oidc_sub") else {}),
        }
        for name, rec in users.items()
    }
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        USERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def seed_default_admin() -> None:
    if read_users():
        return
    write_users({"admin": {"password": hash_password("admin"), "role": "admin", "source": "local"}})
    logger.info("Создан пользователь по умолчанию admin/admin")


def role_of(username: str) -> str:
    rec = read_users().get(username)
    if rec is None:
        return "editor"
    return rec.get("role") if rec.get("role") in ROLES else "editor"


def admin_count(users: dict[str, dict[str, Any]] | None = None) -> int:
    store = users if users is not None else read_users()
    return sum(1 for rec in store.values() if rec.get("role") == "admin")


def cleanup_sessions() -> None:
    now = time.time()
    expired = [token for token, session in SESSIONS.items() if session["expires_at"] <= now]
    for token in expired:
        SESSIONS.pop(token, None)


def create_session(username: str) -> str:
    cleanup_sessions()
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"username": username, "expires_at": time.time() + SESSION_TTL_SECONDS}
    return token


def drop_sessions(username: str, keep: str | None = None) -> None:
    for token, session in list(SESSIONS.items()):
        if session.get("username") == username and token != keep:
            SESSIONS.pop(token, None)


def current_user(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = SESSIONS.get(token)
    if not session:
        return None
    if session["expires_at"] <= time.time():
        SESSIONS.pop(token, None)
        return None
    session["expires_at"] = time.time() + SESSION_TTL_SECONDS
    return str(session["username"])


def require_user(request: Request) -> str:
    username = current_user(request)
    if username is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return username


def require_admin(request: Request) -> str:
    username = require_user(request)
    if role_of(username) != "admin":
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return username


def session_cookie_kwargs() -> dict[str, Any]:
    return {
        "max_age": SESSION_TTL_SECONDS,
        "httponly": True,
        "samesite": "lax",
        "secure": COOKIE_SECURE,
    }

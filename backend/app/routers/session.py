from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import Request, Response

from .. import auth
from ..auth import COOKIE_SECURE, SESSION_COOKIE
from ..llm import styleguide_store
from .infra import DATA_DIR, PREFS_FILE, _prefs_lock

LOGIN_ATTEMPTS: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = 300

_cors_raw = os.getenv("PROOFREADER_CORS_ORIGINS", "")
# Список явных origin'ов. Пустой список означает «только same-origin»: с
# allow_credentials=True нельзя ставить "*", иначе это либо не работает в
# браузере, либо (после «починки») открывает кросс-доменный доступ к сессии.
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")

def _session_payload(username: str) -> dict[str, Any]:
    return {
        "username": username,
        "role": auth.role_of(username),
        "source": auth.read_users().get(username, {}).get("source") or "local",
        "jira_base_url": JIRA_BASE_URL,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, **auth.session_cookie_kwargs())


auth.seed_default_admin()
styleguide_store.seed_default()


def _read_prefs() -> dict[str, dict]:
    with _prefs_lock:
        if not PREFS_FILE.exists():
            return {}
        try:
            data = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def _write_prefs(prefs: dict[str, dict]) -> None:
    with _prefs_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PREFS_FILE.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_user_styleguide_id(user: str) -> str:
    """id выбранного пользователем гайда; если его нет — встроенный «Базовый»."""
    prefs = _read_prefs()
    chosen = (prefs.get(user) or {}).get("styleguide_id")
    if chosen and styleguide_store.get_guide(chosen) is not None:
        return chosen
    return styleguide_store.DEFAULT_ID


def _set_user_styleguide_id(user: str, styleguide_id: str) -> None:
    prefs = _read_prefs()
    prefs.setdefault(user, {})["styleguide_id"] = styleguide_id
    _write_prefs(prefs)


def _client_ip(request: Request) -> str:
    xr = request.headers.get("x-real-ip")
    if xr:
        return xr.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(key: str) -> bool:
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(key, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW]
    LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) < MAX_LOGIN_ATTEMPTS


def _record_failed_login(key: str) -> None:
    LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())

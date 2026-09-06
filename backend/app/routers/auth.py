from __future__ import annotations

from pydantic import BaseModel

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .. import audit, auth
from ..auth import SESSION_COOKIE, COOKIE_SECURE
from .. import oidc as oidc_login
from ..auth import require_user
from .session import LOGIN_ATTEMPTS, JIRA_BASE_URL, _check_rate_limit, _client_ip, _record_failed_login, _session_payload, _set_session_cookie

router = APIRouter(tags=["Авторизация"])

class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class UserCreate(BaseModel):
    username: str
    password: str | None = None
    role: str = "editor"

class UserPatch(BaseModel):
    role: str | None = None

@router.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    username = body.username.strip()
    ip = _client_ip(request)
    pair_key = f"{ip}:{username}"
    ip_key = f"ip:{ip}"

    if not _check_rate_limit(pair_key) or not _check_rate_limit(ip_key):
        raise HTTPException(429, "Слишком много попыток. Подожди 5 минут.")

    users = auth.read_users()
    rec = users.get(username)
    hashed = (rec or {}).get("password") or ""
    if rec is None or rec.get("source") == "oidc" or not auth.check_password(body.password, hashed):
        _record_failed_login(pair_key)
        _record_failed_login(ip_key)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    LOGIN_ATTEMPTS.pop(pair_key, None)
    token = auth.create_session(username)
    audit.append("login", username, source="local")
    response = Response(
        content=json.dumps(_session_payload(username), ensure_ascii=False),
        media_type="application/json",
    )
    _set_session_cookie(response, token)
    return response


@router.get("/api/auth/oidc/start")
async def oidc_start():
    if not oidc_login.configured():
        raise HTTPException(404, "OIDC не настроен")
    return RedirectResponse(await oidc_login.start_url(), status_code=302)


@router.get("/api/auth/oidc/callback")
async def oidc_callback(code: str = "", state: str = ""):
    if not oidc_login.configured():
        raise HTTPException(404, "OIDC не настроен")
    if not code or not state:
        raise HTTPException(400, "Нет кода авторизации")
    info = await oidc_login.exchange(code, state)
    users = auth.read_users()
    username = info["username"]
    existing = next(
        (name for name, rec in users.items() if rec.get("oidc_sub") == info["sub"]),
        username if username in users else None,
    )
    if existing:
        username = existing
        rec = users[username]
        rec["source"] = "oidc"
        rec["oidc_sub"] = info["sub"]
        rec["password"] = ""
        if rec.get("role") != "admin":
            rec["role"] = info["role"]
    else:
        users[username] = {
            "password": "",
            "role": info["role"],
            "source": "oidc",
            "oidc_sub": info["sub"],
        }
    auth.write_users(users)
    token = auth.create_session(username)
    audit.append("login", username, source="oidc")
    response = RedirectResponse("/#/check", status_code=302)
    _set_session_cookie(response, token)
    return response


@router.get("/api/auth/me")
async def me(request: Request):
    username = auth.current_user(request)
    if username is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return _session_payload(username)


@router.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.SESSIONS.pop(token, None)
    response = Response(content=json.dumps({"ok": True}), media_type="application/json")
    response.delete_cookie(SESSION_COOKIE, samesite="lax", httponly=True, secure=COOKIE_SECURE)
    return response


@router.post("/api/auth/change-password")
async def change_password(body: ChangePasswordRequest, request: Request, user: str = Depends(require_user)):
    rate_key = f"pwchange:{_client_ip(request)}:{user}"
    if not _check_rate_limit(rate_key):
        raise HTTPException(429, "Слишком много попыток. Подожди 5 минут.")

    if len(body.new_password) < auth.MIN_PASSWORD:
        raise HTTPException(400, f"Пароль должен содержать минимум {auth.MIN_PASSWORD} символов")

    users = auth.read_users()
    rec = users.get(user)
    if rec is None or rec.get("source") == "oidc":
        raise HTTPException(400, "Пароль меняется у провайдера входа")
    if not auth.check_password(body.current_password, rec.get("password") or ""):
        _record_failed_login(rate_key)
        raise HTTPException(403, "Текущий пароль неверный")

    LOGIN_ATTEMPTS.pop(rate_key, None)
    rec["password"] = auth.hash_password(body.new_password)
    auth.write_users(users)
    auth.drop_sessions(user, keep=request.cookies.get(SESSION_COOKIE))
    audit.append("password_change", user)
    return {"ok": True}

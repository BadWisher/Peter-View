from __future__ import annotations

from pydantic import BaseModel

import secrets

from fastapi import APIRouter, Depends, HTTPException

from .. import audit, auth
from ..auth import require_admin

router = APIRouter(tags=["Пользователи"])

class UserCreate(BaseModel):
    username: str
    password: str | None = None
    role: str = "editor"


class UserPatch(BaseModel):
    role: str | None = None

@router.get("/api/users")
async def list_users(_user: str = Depends(require_admin)):
    users = auth.read_users()
    return {
        "users": [
            {"username": name, "role": rec.get("role"), "source": rec.get("source") or "local"}
            for name, rec in sorted(users.items())
        ]
    }


@router.post("/api/users")
async def create_user(body: UserCreate, actor: str = Depends(require_admin)):
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Укажи логин")
    role = body.role if body.role in auth.ROLES else "editor"
    users = auth.read_users()
    if username in users:
        raise HTTPException(409, "Такой логин уже есть")
    password = (body.password or "").strip() or secrets.token_urlsafe(9)
    if len(password) < auth.MIN_PASSWORD:
        raise HTTPException(400, f"Пароль должен содержать минимум {auth.MIN_PASSWORD} символов")
    users[username] = {"password": auth.hash_password(password), "role": role, "source": "local"}
    auth.write_users(users)
    audit.append("user_create", actor, target=username, role=role)
    return {"username": username, "password": password, "role": role}


@router.patch("/api/users/{username}")
async def patch_user(username: str, body: UserPatch, actor: str = Depends(require_admin)):
    users = auth.read_users()
    rec = users.get(username)
    if rec is None:
        raise HTTPException(404, "Пользователь не найден")
    if body.role:
        if body.role not in auth.ROLES:
            raise HTTPException(400, "Неизвестная роль")
        if rec.get("role") == "admin" and body.role != "admin" and auth.admin_count(users) <= 1:
            raise HTTPException(400, "Нельзя снять последнего администратора")
        rec["role"] = body.role
        auth.write_users(users)
        audit.append("role_change", actor, target=username, role=body.role)
    return {"username": username, "role": rec["role"], "source": rec.get("source") or "local"}


@router.delete("/api/users/{username}")
async def delete_user(username: str, actor: str = Depends(require_admin)):
    users = auth.read_users()
    rec = users.get(username)
    if rec is None:
        raise HTTPException(404, "Пользователь не найден")
    if username == actor:
        raise HTTPException(400, "Нельзя удалить себя")
    if rec.get("role") == "admin" and auth.admin_count(users) <= 1:
        raise HTTPException(400, "Нельзя удалить последнего администратора")
    del users[username]
    auth.write_users(users)
    auth.drop_sessions(username)
    audit.append("user_delete", actor, target=username)
    return {"ok": True}

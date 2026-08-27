from __future__ import annotations

import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

_pending: dict[str, dict[str, Any]] = {}
_meta: dict[str, Any] | None = None


def configured() -> bool:
    return bool(os.getenv("OIDC_ISSUER", "").strip() and os.getenv("OIDC_CLIENT_ID", "").strip())


def _issuer() -> str:
    return os.getenv("OIDC_ISSUER", "").strip().rstrip("/")


def _redirect() -> str:
    return os.getenv("OIDC_REDIRECT_URI", "").strip()


def admin_groups() -> set[str]:
    raw = os.getenv("OIDC_ADMIN_GROUPS", "")
    return {part.strip() for part in raw.split(",") if part.strip()}


async def discover() -> dict[str, Any]:
    global _meta
    if _meta:
        return _meta
    issuer = _issuer()
    if not issuer:
        raise HTTPException(404, "OIDC не настроен")
    url = f"{issuer}/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(url)
        response.raise_for_status()
        _meta = response.json()
    return _meta


async def start_url() -> str:
    meta = await discover()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    _pending[state] = {"nonce": nonce, "exp": time.time() + 600}
    params = {
        "response_type": "code",
        "client_id": os.getenv("OIDC_CLIENT_ID", ""),
        "redirect_uri": _redirect(),
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
    }
    return f"{meta['authorization_endpoint']}?{urlencode(params)}"


def _groups_from_claims(claims: dict[str, Any]) -> set[str]:
    groups = claims.get("groups") or claims.get("roles") or []
    if isinstance(groups, str):
        groups = [groups]
    realm = (claims.get("realm_access") or {}).get("roles") or []
    return {str(item) for item in list(groups) + list(realm)}


async def exchange(code: str, state: str) -> dict[str, Any]:
    pending = _pending.pop(state, None)
    if not pending or pending["exp"] < time.time():
        raise HTTPException(400, "Сессия входа устарела, попробуй снова")
    meta = await discover()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect(),
        "client_id": os.getenv("OIDC_CLIENT_ID", ""),
        "client_secret": os.getenv("OIDC_CLIENT_SECRET", ""),
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(meta["token_endpoint"], data=data)
        if token_resp.status_code >= 400:
            raise HTTPException(400, "Провайдер не выдал токен")
        tokens = token_resp.json()
        userinfo: dict[str, Any] = {}
        if meta.get("userinfo_endpoint") and tokens.get("access_token"):
            info = await client.get(
                meta["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if info.status_code < 400:
                userinfo = info.json()
    claims = {**userinfo}
    username = (
        str(claims.get("preferred_username") or claims.get("email") or claims.get("sub") or "")
        .strip()
    )
    if not username:
        raise HTTPException(400, "Провайдер не вернул имя пользователя")
    groups = _groups_from_claims(claims)
    role = "admin" if groups & admin_groups() else "editor"
    return {
        "username": username[:80],
        "role": role,
        "sub": str(claims.get("sub") or username),
    }

from __future__ import annotations

from pydantic import BaseModel

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from .. import audit
from ..auth import require_admin
from ..llm import client as llm_client
from ..llm import rag as llm_rag
from ..llm import settings as llm_settings

router = APIRouter(tags=["Настройки"])

class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_concurrency: int | None = None
    llm_timeout: float | None = None
    llm_json_mode: bool | None = None
    llm_reasoning_effort: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None

@router.get("/api/settings")
async def get_settings(_user: str = Depends(require_admin)):
    return llm_settings.get_masked()


@router.put("/api/settings")
async def put_settings(body: SettingsUpdate, user: str = Depends(require_admin)):
    patch = {k: v for k, v in body.dict().items() if v is not None}
    if not patch:
        raise HTTPException(400, "Нет полей для обновления")
    try:
        llm_settings.update(patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.append("settings_update", user, fields=sorted(patch.keys()))
    return llm_settings.get_masked()


@router.post("/api/settings/test")
async def test_settings(_user: str = Depends(require_admin)):
    """Проверяет доступность LLM и эмбеддингов с текущими настройками."""
    result: dict[str, Any] = {}
    try:
        await asyncio.wait_for(llm_client.healthcheck(), timeout=30)
        result["llm"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["llm"] = {"ok": False, "error": str(e)}
    try:
        await asyncio.wait_for(asyncio.to_thread(llm_rag.healthcheck), timeout=30)
        result["embedding"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["embedding"] = {"ok": False, "error": str(e)}
    return result


# --- История проверок и статистика правил -----------------------------------

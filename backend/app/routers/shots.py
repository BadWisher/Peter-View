from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from ..auth import require_user
from ..llm import shot_templates

router = APIRouter(tags=["Скриншоты"])

class ShotTemplateCreate(BaseModel):
    name: str
    width: int


@router.get("/api/screenshot-templates")
async def list_screenshot_templates(_user: str = Depends(require_user)):
    return {"templates": shot_templates.list_templates()}


@router.post("/api/screenshot-templates")
async def add_screenshot_template(body: ShotTemplateCreate, _user: str = Depends(require_user)):
    try:
        return shot_templates.add_template(body.name, body.width)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/screenshot-templates/{template_id}")
async def delete_screenshot_template(template_id: str, _user: str = Depends(require_user)):
    try:
        shot_templates.delete_template(template_id)
    except KeyError:
        raise HTTPException(404, "Шаблон не найден")
    return {"ok": True}

from __future__ import annotations

from pydantic import BaseModel

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from ..auth import require_user
from ..llm import watch_run, watch_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Мониторинг"])

_watch_running: set[str] = set()


def _watch_group_out(group: dict) -> dict:
    return {**group, "running": group["id"] in _watch_running}


def _watch_page_out(page: dict) -> dict:
    return {**page, "running": f"page:{page['id']}" in _watch_running or page["group_id"] in _watch_running}

class WatchGroupCreate(BaseModel):
    name: str
    auth_kind: str = "none"
    login_url: str = ""
    username: str = ""
    password: str = ""
    username_field: str = "username"
    password_field: str = "password"


class WatchGroupPatch(BaseModel):
    name: str | None = None
    auth_kind: str | None = None
    login_url: str | None = None
    username: str | None = None
    password: str | None = None
    username_field: str | None = None
    password_field: str | None = None


class WatchPageCreate(BaseModel):
    url: str
    title: str = ""


class WatchPagePatch(BaseModel):
    url: str | None = None
    title: str | None = None
    enabled: bool | None = None

@router.get("/api/watch/groups")
async def watch_list_groups(_user: str = Depends(require_user)):
    return {"groups": [_watch_group_out(item) for item in watch_store.list_groups()]}


@router.post("/api/watch/groups")
async def watch_create_group(body: WatchGroupCreate, user: str = Depends(require_user)):
    try:
        group = watch_store.create_group(
            body.name,
            auth_kind=body.auth_kind,
            login_url=body.login_url,
            username=body.username,
            password=body.password,
            username_field=body.username_field,
            password_field=body.password_field,
            created_by=user,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _watch_group_out(group)


@router.get("/api/watch/groups/{group_id}")
async def watch_get_group(group_id: str, _user: str = Depends(require_user)):
    group = watch_store.get_group(group_id)
    if group is None:
        raise HTTPException(404, "Группа не найдена")
    return {
        **_watch_group_out(group),
        "pages": [_watch_page_out(page) for page in watch_store.list_pages(group_id)],
    }


@router.patch("/api/watch/groups/{group_id}")
async def watch_patch_group(group_id: str, body: WatchGroupPatch, _user: str = Depends(require_user)):
    fields = body.model_dump(exclude_unset=True)
    try:
        group = watch_store.update_group(group_id, **fields)
    except KeyError:
        raise HTTPException(404, "Группа не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _watch_group_out(group)


@router.delete("/api/watch/groups/{group_id}")
async def watch_delete_group(group_id: str, _user: str = Depends(require_user)):
    if watch_store.get_group(group_id) is None:
        raise HTTPException(404, "Группа не найдена")
    watch_store.delete_group(group_id)
    return {"ok": True}


@router.post("/api/watch/groups/{group_id}/pages")
async def watch_add_page(group_id: str, body: WatchPageCreate, _user: str = Depends(require_user)):
    try:
        page = watch_store.add_page(group_id, body.url, body.title)
    except KeyError:
        raise HTTPException(404, "Группа не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return page


@router.patch("/api/watch/pages/{page_id}")
async def watch_patch_page(page_id: str, body: WatchPagePatch, _user: str = Depends(require_user)):
    fields = body.model_dump(exclude_unset=True)
    try:
        page = watch_store.update_page(page_id, **fields)
    except KeyError:
        raise HTTPException(404, "Адрес не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return page


@router.delete("/api/watch/pages/{page_id}")
async def watch_delete_page(page_id: str, _user: str = Depends(require_user)):
    if watch_store.get_page(page_id) is None:
        raise HTTPException(404, "Адрес не найден")
    watch_store.delete_page(page_id)
    return {"ok": True}


@router.post("/api/watch/groups/{group_id}/run")
async def watch_run_group(group_id: str, _user: str = Depends(require_user)):
    if watch_store.get_group(group_id) is None:
        raise HTTPException(404, "Группа не найдена")
    if group_id in _watch_running:
        return {"status": "running"}
    _watch_running.add(group_id)

    async def _go():
        try:
            await watch_run.check_group(group_id)
        except Exception:  # noqa: BLE001
            logger.exception("Проверка группы мониторинга %s не удалась", group_id)
        finally:
            _watch_running.discard(group_id)

    asyncio.create_task(_go())
    return {"status": "started"}


@router.post("/api/watch/pages/{page_id}/run")
async def watch_run_page(page_id: str, _user: str = Depends(require_user)):
    page = watch_store.get_page(page_id)
    if page is None:
        raise HTTPException(404, "Адрес не найден")
    group_id = page["group_id"]
    key = f"page:{page_id}"
    if key in _watch_running or group_id in _watch_running:
        return {"status": "running"}
    _watch_running.add(key)

    async def _go():
        try:
            await watch_run.check_page(page_id)
        except Exception:  # noqa: BLE001
            logger.exception("Проверка адреса мониторинга %s не удалась", page_id)
        finally:
            _watch_running.discard(key)

    asyncio.create_task(_go())
    return {"status": "started"}


@router.get("/api/watch/pages/{page_id}/diff")
async def watch_page_diff(page_id: str, _user: str = Depends(require_user)):
    try:
        return watch_run.page_diff(page_id)
    except KeyError:
        raise HTTPException(404, "Адрес не найден")


@router.get("/api/watch/pages/{page_id}/copy")
async def watch_page_copy(page_id: str, _user: str = Depends(require_user)):
    # Живая копия для песочницы фрейма: полный html-документ с подсветкой.
    # Отдельным запросом, а не в diff: тело тяжёлое, а список и diff
    # должны оставаться быстрыми. Разметка вычищена при записи
    # (без скриптов и on*-атрибутов), фрейм сверху в sandbox без
    # скриптов/форм/топ-навигации — клики остаются внутри копии.
    try:
        payload = watch_run.page_copy(page_id)
    except KeyError:
        raise HTTPException(404, "Адрес не найден")
    return Response(content=payload, media_type="text/html; charset=utf-8")


@router.get("/api/watch/pages/{page_id}/history")
async def watch_page_history(page_id: str, _user: str = Depends(require_user)):
    if watch_store.get_page(page_id) is None:
        raise HTTPException(404, "Адрес не найден")
    return {"items": watch_store.list_snapshots(page_id)}

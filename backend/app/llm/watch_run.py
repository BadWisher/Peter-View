"""Сбор снимков внешних страниц и сравнение с прошлым днём."""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import hashlib
import logging
import os
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..extractors import extract_html
from ..net_guard import BlockedURLError, safe_request
from . import watch_store as store

logger = logging.getLogger(__name__)

USER_AGENT = os.getenv(
    "WATCH_USER_AGENT",
    "Mozilla/5.0 (compatible; PeterViewWatch/1.0)",
)
WATCH_HOUR = int(os.getenv("PROOFREADER_WATCH_HOUR", "4"))
CONTEXT_LINES = 2


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_text(html: str) -> str:
    return extract_html(html, include_chrome=False).strip()


def collapse_hunks(hunks: list[dict]) -> list[dict]:
    collapsed: list[dict] = []
    for hunk in hunks:
        lines = hunk["lines"]
        if hunk["op"] == "eq" and len(lines) > CONTEXT_LINES * 2 + 2:
            collapsed.append({"op": "eq", "lines": lines[:CONTEXT_LINES]})
            collapsed.append({"op": "skip", "count": len(lines) - CONTEXT_LINES * 2})
            collapsed.append({"op": "eq", "lines": lines[-CONTEXT_LINES:]})
        else:
            collapsed.append(hunk)
    return collapsed


def text_hunks(old: str, new: str) -> list[dict]:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    hunks: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old_lines, b=new_lines).get_opcodes():
        if tag == "equal":
            hunks.append({"op": "eq", "lines": old_lines[i1:i2]})
        elif tag == "replace":
            hunks.append({"op": "del", "lines": old_lines[i1:i2]})
            hunks.append({"op": "add", "lines": new_lines[j1:j2]})
        elif tag == "delete":
            hunks.append({"op": "del", "lines": old_lines[i1:i2]})
        elif tag == "insert":
            hunks.append({"op": "add", "lines": new_lines[j1:j2]})
    return collapse_hunks(hunks)


def _guess_fields(form) -> tuple[str, str]:
    user_name = ""
    pass_name = ""
    for inp in form.find_all("input"):
        name = (inp.get("name") or "").strip()
        if not name:
            continue
        itype = (inp.get("type") or "text").lower()
        if itype == "password" and not pass_name:
            pass_name = name
        elif itype in ("text", "email", "tel") and not user_name:
            user_name = name
    return user_name or "username", pass_name or "password"


async def _form_login(
    client: httpx.AsyncClient,
    group: dict,
) -> None:
    login_url = group["login_url"]
    username = group.get("username") or ""
    password = group.get("password") or ""
    if not username or not password:
        raise ValueError("Для формы входа нужны логин и пароль")
    page = await safe_request(client, "GET", login_url)
    soup = BeautifulSoup(page.text, "lxml")
    form = soup.find("form")
    action = login_url
    payload: dict[str, str] = {}
    user_field = group.get("username_field") or "username"
    pass_field = group.get("password_field") or "password"
    if form:
        action = urljoin(login_url, form.get("action") or login_url)
        for inp in form.find_all("input"):
            name = (inp.get("name") or "").strip()
            if not name:
                continue
            itype = (inp.get("type") or "text").lower()
            if itype in ("submit", "button", "image", "file"):
                continue
            payload[name] = inp.get("value") or ""
        guessed_user, guessed_pass = _guess_fields(form)
        if user_field not in payload:
            user_field = guessed_user
        if pass_field not in payload:
            pass_field = guessed_pass
    payload[user_field] = username
    payload[pass_field] = password
    resp = await safe_request(client, "POST", action, data=payload)
    if resp.status_code >= 400:
        raise ValueError(f"Вход не удался (HTTP {resp.status_code})")


async def _login(client: httpx.AsyncClient, group: dict) -> httpx.Auth | None:
    kind = group.get("auth_kind") or "none"
    if kind == "basic":
        username = group.get("username") or ""
        password = group.get("password") or ""
        if not username or not password:
            raise ValueError("Для HTTP Basic нужны логин и пароль")
        return httpx.BasicAuth(username, password)
    if kind == "form":
        await _form_login(client, group)
        return None
    return None


async def _fetch_page(client: httpx.AsyncClient, url: str, auth: httpx.Auth | None) -> str:
    resp = await safe_request(client, "GET", url, auth=auth)
    if resp.status_code >= 400:
        raise ValueError(f"Страница недоступна (HTTP {resp.status_code})")
    return snapshot_text(resp.text)


async def check_page(page_id: str, client: httpx.AsyncClient | None = None, auth: httpx.Auth | None = None) -> dict:
    page = store.get_page(page_id)
    if page is None:
        raise KeyError("Адрес не найден")
    group = store.get_group(page["group_id"], with_secret=True)
    if group is None:
        raise KeyError("Группа не найдена")
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": USER_AGENT},
        )
    assert client is not None
    try:
        if own_client:
            auth = await _login(client, group)
        text = await _fetch_page(client, page["url"], auth)
        digest = fingerprint(text)
        previous = store.latest_snapshots(page_id, limit=1)
        changed = bool(previous) and previous[0]["content_hash"] != digest
        if not previous:
            changed = False
        store.record_snapshot(page_id, text=text, content_hash=digest, changed=changed)
        return store.get_page(page_id)  # type: ignore[return-value]
    except (BlockedURLError, ValueError, httpx.HTTPError) as exc:
        message = str(exc)
        store.record_snapshot(page_id, text="", content_hash="", changed=False, error=message)
        logger.warning("Наблюдение %s: %s", page["url"], message)
        return store.get_page(page_id)  # type: ignore[return-value]
    finally:
        if own_client:
            await client.aclose()


async def check_group(group_id: str) -> dict:
    group = store.get_group(group_id, with_secret=True)
    if group is None:
        raise KeyError("Группа не найдена")
    pages = [page for page in store.list_pages(group_id) if page["enabled"]]
    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
        try:
            auth = await _login(client, group)
        except (BlockedURLError, ValueError, httpx.HTTPError) as exc:
            message = str(exc)
            for page in pages:
                store.record_snapshot(page["id"], text="", content_hash="", changed=False, error=message)
            store.mark_group_run(group_id)
            return store.get_group(group_id)  # type: ignore[return-value]
        for page in pages:
            await check_page(page["id"], client=client, auth=auth)
            await asyncio.sleep(0.3)
    store.mark_group_run(group_id)
    return store.get_group(group_id)  # type: ignore[return-value]


async def check_all_groups() -> None:
    for group in store.list_groups():
        try:
            await check_group(group["id"])
        except Exception:  # noqa: BLE001
            logger.exception("Наблюдение группы %s не выполнено", group["id"])


def due_today() -> bool:
    today = dt.datetime.now().strftime("%Y-%m-%d")
    if store.get_daily_stamp() == today:
        return False
    return dt.datetime.now().hour >= WATCH_HOUR


async def run_daily_if_due() -> None:
    if not due_today():
        return
    await check_all_groups()
    store.set_daily_stamp(dt.datetime.now().strftime("%Y-%m-%d"))


def page_diff(page_id: str) -> dict:
    page = store.get_page(page_id)
    if page is None:
        raise KeyError("Адрес не найден")
    snaps = store.latest_snapshots(page_id, limit=2)
    if not snaps:
        return {"page": page, "hunks": [], "previous": None, "current": None}
    current = snaps[0]
    previous = snaps[1] if len(snaps) > 1 else None
    hunks = text_hunks(previous["text"] if previous else "", current["text"]) if previous else []
    return {
        "page": page,
        "current": {
            "checked_at": current["checked_at"],
            "changed": bool(current["changed"]),
            "error": current["error"],
        },
        "previous": {
            "checked_at": previous["checked_at"],
            "changed": bool(previous["changed"]),
            "error": previous["error"],
        } if previous else None,
        "hunks": hunks,
    }

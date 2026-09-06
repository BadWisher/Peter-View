"""Сбор снимков внешних страниц и сравнение с прошлым днём."""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import hashlib
import json
import logging
import os
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..extractors import extract_html, normalize_spaces
from ..net_guard import BlockedURLError, safe_request
from . import watch_store as store
from . import watch_dom
from . import watch_render
from .watch_dom import _VOLATILE

logger = logging.getLogger(__name__)

USER_AGENT = os.getenv(
    "WATCH_USER_AGENT",
    "Mozilla/5.0 (compatible; PeterViewWatch/1.0)",
)
WATCH_HOUR = int(os.getenv("PROOFREADER_WATCH_HOUR", "4"))
CONTEXT_LINES = 2
# Слишком короткий текст почти всегда означает пустой каркас страницы
# (JS-портал без рендера, каптча, заглушка). Такое считаем ошибкой съёма,
# а не «без изменений», иначе наблюдение молча замирает.
MIN_SNAPSHOT_CHARS = int(os.getenv("PROOFREADER_WATCH_MIN_CHARS", "24"))


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_text(html: str) -> str:
    return extract_html(html, include_chrome=False).strip()


def normalized_text(text: str) -> str:
    out = []
    for line in text.splitlines():
        line = normalize_spaces(line)
        for pat in _VOLATILE:
            line = pat.sub("", line)
        line = re.sub(r"\s+", " ", line).strip(" -–—•·")
        if line:
            out.append(line)
    return "\n".join(out)


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
    return collapse_hunks(mark_word_diff(hunks))


def mark_word_diff(hunks: list[dict]) -> list[dict]:
    out: list[dict] = []
    i = 0
    while i < len(hunks):
        cur = hunks[i]
        nxt = hunks[i + 1] if i + 1 < len(hunks) else None
        if (
            cur["op"] == "del" and nxt and nxt["op"] == "add"
            and len(cur["lines"]) == 1 and len(nxt["lines"]) == 1
            and difflib.SequenceMatcher(a=cur["lines"][0].split(), b=nxt["lines"][0].split()).ratio() > 0.3
        ):
            old_words = cur["lines"][0].split()
            new_words = nxt["lines"][0].split()
            keep = [False] * len(new_words)
            for match in difflib.SequenceMatcher(a=old_words, b=new_words).get_matching_blocks():
                for j in range(match.b, min(match.b + match.size, len(keep))):
                    keep[j] = True
            out.append({**cur, "words": old_words})
            out.append({**nxt, "words": new_words, "same": keep})
            i += 2
            continue
        out.append(cur)
        i += 1
    return out


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
    form = None
    for candidate in soup.find_all("form"):
        for inp in candidate.find_all("input"):
            if (inp.get("type") or "").lower() == "password":
                form = candidate
                break
        if form is not None:
            break
    form = form or soup.find("form")
    if form is None:
        raise ValueError(
            "На странице входа нет формы (возможно, вход через JS или SSO — такой портал наблюдение не поддерживает)"
        )
    action = urljoin(login_url, form.get("action") or login_url)
    payload: dict[str, str] = {}
    user_field = group.get("username_field") or "username"
    pass_field = group.get("password_field") or "password"
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
    again = BeautifulSoup(resp.text, "lxml")
    if again.find("input", {"type": "password"}):
        raise ValueError("Похоже, вход не удался: портал снова показал форму входа")


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


async def _fetch_page(client: httpx.AsyncClient, url: str, auth: httpx.Auth | None) -> tuple[str, str]:
    resp = await safe_request(client, "GET", url, auth=auth)
    if resp.status_code == 401:
        raise ValueError("Портал просит войти заново (HTTP 401) — проверь логин и пароль группы")
    if resp.status_code >= 400:
        raise ValueError(f"Страница недоступна (HTTP {resp.status_code})")
    html = resp.text
    rendered = False
    text = snapshot_text(html)
    if len(text) < MIN_SNAPSHOT_CHARS and watch_render.render_available():
        try:
            html = await watch_render.render_html(url)
            rendered = True
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Рендер %s не удался: %s", url, exc)
    text = snapshot_text(html)
    if len(text) < MIN_SNAPSHOT_CHARS:
        hint = "" if rendered else (
            " — возможно, нужен JS (поставь playwright и chromium), либо портал отдал заглушку"
            if watch_render.render_available() is False else " — возможно, нужен JS или портал отдал заглушку"
        )
        raise ValueError(f"Со страницы пришло почти пусто ({len(text)} символов){hint}")
    soup = BeautifulSoup(html, "lxml")
    has_pass = any(
        (inp.get("type") or "").lower() == "password" for inp in soup.find_all("input")
    )
    lowered = html.lower()
    if has_pass and any(
        mark in lowered for mark in ("парол", "password", "sign in", "log in", "войти", "вход")
    ):
        raise ValueError("Портал снова показал форму входа — сессия протухла, проверь пароль группы")
    return html, rendered


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
        html, _rendered = await _fetch_page(client, page["url"], auth)
        text = snapshot_text(html)
        nodes = watch_dom.snapshot_nodes(html)
        body = watch_dom.cleaned_body(html)
        digest = fingerprint(normalized_text(text))
        struct = watch_dom.fingerprint_nodes(nodes)
        previous = store.latest_snapshots(page_id, limit=1)
        changed = False
        if previous:
            changed = previous[0]["content_hash"] != digest or (previous[0].get("struct_hash") or "") != struct
        store.record_snapshot(
            page_id, text=text, content_hash=digest, changed=changed,
            struct_hash=struct, dom=json.dumps(nodes, ensure_ascii=False),
            body=body,
        )
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


def _pair_snaps(page_id: str) -> tuple[dict | None, dict | None]:
    snaps = store.latest_snapshots(page_id, limit=20)
    if not snaps:
        return None, None
    changed_at = next((i for i, snap in enumerate(snaps) if snap.get("changed")), None)
    if changed_at is None:
        # Все прогоны холостые: показывать нечего, пару не выдумываем.
        return snaps[0], None
    current = snaps[changed_at]
    previous = snaps[changed_at + 1] if changed_at + 1 < len(snaps) else None
    return current, previous


def _loads_nodes(raw: str) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        # снимки до подъёма DOM_CAP хранили обрезанный JSON; достаём целые узлы
        end = (raw or "").rfind("},")
        if end < 0:
            return []
        try:
            data = json.loads(raw[:end] + "]")
        except (ValueError, TypeError):
            return []
    return data if isinstance(data, list) else []


def _hunks_and_ui(current: dict | None, previous: dict | None) -> tuple[list[dict], list[dict], list[dict]]:
    if not previous or not (current.get("dom") or previous.get("dom")):
        hunks = text_hunks(previous["text"] if previous else "", current["text"]) if (current and previous) else []
        return hunks, [], []
    old_nodes = _loads_nodes(previous.get("dom") or "")
    new_nodes = _loads_nodes(current.get("dom") or "")
    ui = watch_dom.diff_nodes(old_nodes, new_nodes)
    marks = [{"path": event.get("path") or "", "kind": event.get("kind") or ""}
             for event in ui if event.get("path") and event.get("kind") != "more"]
    hunks = text_hunks(normalized_text(previous["text"]) if previous else "",
                       normalized_text(current["text"])) if previous else []
    return hunks, ui, marks


def _copy_pair(previous: dict, current: dict) -> tuple[list[dict], list[dict]]:
    return _loads_nodes(previous.get("dom") or ""), _loads_nodes(current.get("dom") or "")


def page_diff(page_id: str) -> dict:
    page = store.get_page(page_id)
    if page is None:
        raise KeyError("Адрес не найден")
    current, previous = _pair_snaps(page_id)
    if not current:
        return {"page": page, "hunks": [], "ui": [], "marks": [], "has_copy": False, "previous": None, "current": None}
    hunks, ui, marks = _hunks_and_ui(current, previous)
    has_copy = bool(previous) and bool(current.get("body"))
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
        "ui": ui,
        "marks": marks,
        "has_copy": has_copy,
    }


def page_copy(page_id: str) -> str:
    page = store.get_page(page_id)
    if page is None:
        raise KeyError("Адрес не найден")
    current, previous = _pair_snaps(page_id)
    if not current:
        return ""
    body = current.get("body") or ""
    if previous:
        old_nodes, new_nodes = _copy_pair(previous, current)
        ui = watch_dom.diff_nodes(old_nodes, new_nodes)
        body = watch_dom.mark_copy(body, old_nodes, new_nodes, ui)
    url = (page.get("url") or "").replace('"', "")
    return watch_dom.copy_document(url, body)

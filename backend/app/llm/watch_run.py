"""Сбор снимков внешних страниц и сравнение с прошлым днём."""

from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import hashlib
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


# Мусор, который меняется сам по себе и не означает правку регламента:
# даты, время, счётчики, длинные токены. Маскируем перед сравнением —
# по сырому тексту хэш тоже храним, чтобы ничего не потерять.
_VOLATILE = [
    re.compile(r"\b\d{2}\.\d{2}\.\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?"),  # 05.09.2026, 05.09.2026 18:20
    re.compile(r"\b\d{2}:\d{2}(?::\d{2})?\b"),  # время
    re.compile(r"\b[0-9a-f]{16,}\b", re.I),  # csrf-токены и прочий hex
    re.compile(r"\b\d[\d\s]*просмотр\w*", re.I),
    re.compile(r"обновлено.*", re.I),  # строка «обновлено ...» целиком
]


def normalized_text(text: str) -> str:
    out = []
    for line in text.splitlines():
        line = normalize_spaces(line)
        for pat in _VOLATILE:
            line = pat.sub("…", line)
        line = re.sub(r"\s+", " ", line).strip()
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
    """В паре del/add из одной строки помечаем, какие слова новые, — фронт их подсветит."""
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
    form = soup.find("form")
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
    # Многие порталы при неверном пароле отдают 200 с той же формой входа —
    # проверяем, что после POST формы на странице больше нет.
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
    """Возвращает (сырой html, отрендерен ли через браузер).

    Сначала пробуем голый HTTP — это быстро и хватает большинству регламентов.
    Если со страницы пришло почти пусто, а рендер доступен — открываем её
    в headless Chromium и забираем DOM после JS. Пустой каркас SPA больше
    не молчит как «без изменений», а либо дорисовывается, либо честно
    падает в ошибку.
    """
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
    # Сессия могла протухнуть посреди прогона: портал отдал страницу входа.
    # Проверяем сырой html, а не вычищенный текст: форма входа может жить
    # в header/nav, которые snapshot_text выкидывает.
    soup = BeautifulSoup(html, "lxml")
    if soup.find("input", {"type": "password"}) and "парол" in html.lower():
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
        digest = fingerprint(normalized_text(text))
        struct = watch_dom.fingerprint_nodes(nodes)
        previous = store.latest_snapshots(page_id, limit=1)
        changed = False
        if previous:
            changed = previous[0]["content_hash"] != digest or (previous[0].get("struct_hash") or "") != struct
        import json

        store.record_snapshot(
            page_id, text=text, content_hash=digest, changed=changed,
            struct_hash=struct, dom=json.dumps(nodes, ensure_ascii=False),
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


def page_diff(page_id: str) -> dict:
    page = store.get_page(page_id)
    if page is None:
        raise KeyError("Адрес не найден")
    snaps = store.latest_snapshots(page_id, limit=2)
    if not snaps:
        return {"page": page, "hunks": [], "ui": [], "previous": None, "current": None}
    current = snaps[0]
    previous = snaps[1] if len(snaps) > 1 else None
    hunks = text_hunks(previous["text"] if previous else "", current["text"]) if previous else []
    ui = []
    if previous and (current.get("dom") or previous.get("dom")):
        import json

        def _nodes(raw: str) -> list[dict]:
            try:
                data = json.loads(raw or "[]")
            except (ValueError, TypeError):
                return []
            return data if isinstance(data, list) else []

        ui = watch_dom.diff_nodes(_nodes(previous.get("dom") or ""), _nodes(current.get("dom") or ""))
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
    }

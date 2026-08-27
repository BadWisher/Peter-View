"""Вычитка и перевод изменённых полей OpenAPI (только по диффу).

Обе операции опциональны и применяются к небольшому набору изменённых сегментов
(дифф последней версии), поэтому работают батчами через общий LLM-клиент (учёт токенов
и кэш – автоматически). Это не тяжёлый многоагентный пайплайн, а точечная проверка
коротких полей по правилам документации API.
"""

from __future__ import annotations

import asyncio
import json
import logging

from .client import complete_json

logger = logging.getLogger(__name__)

BATCH = 20

_RULES = """Правила документации API (в тексте используй короткое тире, не длинное):
- summary: краткий заголовок метода, начинается с глагола в неопределённой форме
  (создать, получить, удалить, обновить), без точки в конце.
- description метода: начинается с глагола в настоящем времени 3-го лица
  (создаёт, возвращает, удаляет), допускает Markdown.
- описание ответа (response): с заглавной буквы; для кодов 4xx/5xx должно быть
  осмысленным описанием ошибки, а не пустым/слишком общим.
- описание поля схемы (schema): краткое и понятное, единообразно с похожими полями.
- базовая грамотность: орфография, пунктуация, грамматика, лишние/недостающие пробелы."""


def _review_system() -> str:
    return (
        "Ты – редактор технической документации API на русском языке. Проверяешь короткие "
        "поля (summary/description) на соответствие правилам и грамотность.\n\n"
        + _RULES
        + "\n\nНе придумывай проблемы: если поле корректно – не добавляй замечание. "
        "Отвечай строго в формате JSON, без markdown и текста вне JSON."
    )


async def _review_batch(batch: list[dict]) -> list[dict]:
    items = [
        {"id": i, "kind": f["kind"], "context": f["context"], "text": f.get("new_text", f.get("text", ""))}
        for i, f in enumerate(batch)
    ]
    user = (
        "Проверь каждое поле ниже. Для проблемных верни замечание со ссылкой на id поля.\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
        + '\n\nФормат ответа JSON:\n'
        '{ "issues": [ { "id": <int>, "severity": "blocker|suggestion|minor", '
        '"message": "что не так", "suggestion": "как исправить" } ] }'
    )
    resp = await complete_json(_review_system(), user)
    out: list[dict] = []
    raw_issues = resp.get("issues", []) if isinstance(resp, dict) else []
    for raw in raw_issues:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(batch)):
            continue
        message = str(raw.get("message", "")).strip()
        if not message:
            continue
        severity = str(raw.get("severity", "")).strip().lower()
        if severity not in ("blocker", "suggestion", "minor"):
            severity = "suggestion"
        f = batch[idx]
        out.append({
            "path_str": f["path_str"],
            "context": f["context"],
            "kind": f["kind"],
            "line": f.get("line"),
            "text": f.get("new_text", f.get("text", "")),
            "severity": severity,
            "message": message,
            "suggestion": str(raw.get("suggestion", "")).strip(),
        })
    return out


async def review_segments(fields: list[dict]) -> list[dict]:
    """Замечания по изменённым полям. Батчи гоняются параллельно."""
    if not fields:
        return []
    batches = [fields[i:i + BATCH] for i in range(0, len(fields), BATCH)]
    results = await asyncio.gather(*(_review_batch(b) for b in batches), return_exceptions=True)
    issues: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("Батч вычитки API упал: %s", r)
            continue
        issues.extend(r)
    return issues


def _translate_system() -> str:
    return (
        "Ты – переводчик технической документации API. Переводишь русские поля на английский "
        "в деловом стиле OpenAPI: summary – с глагола (Create, Get, Delete, Update); "
        "description – настоящее время 3-го лица (Creates, Returns, Deletes). Сохраняй Markdown "
        "и плейсхолдеры. Отвечай строго в формате JSON, без текста вне JSON."
    )


async def _translate_batch(batch: list[dict]) -> dict[str, str]:
    items = [
        {"id": i, "kind": f["kind"], "context": f["context"], "text": f.get("new_text", f.get("text", ""))}
        for i, f in enumerate(batch)
    ]
    user = (
        "Переведи поле text каждого элемента на английский.\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
        + '\n\nФормат ответа JSON:\n{ "translations": [ { "id": <int>, "en": "перевод" } ] }'
    )
    resp = await complete_json(_translate_system(), user)
    out: dict[str, str] = {}
    raw_items = resp.get("translations", []) if isinstance(resp, dict) else []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            idx = int(raw.get("id"))
        except (TypeError, ValueError):
            continue
        if not (0 <= idx < len(batch)):
            continue
        en = str(raw.get("en", "")).strip()
        if en:
            out[batch[idx]["path_str"]] = en
    return out


async def translate_segments(fields: list[dict]) -> dict[str, str]:
    """Перевод изменённых русских полей на английский: {path_str: en_text}."""
    if not fields:
        return {}
    batches = [fields[i:i + BATCH] for i in range(0, len(fields), BATCH)]
    results = await asyncio.gather(*(_translate_batch(b) for b in batches), return_exceptions=True)
    merged: dict[str, str] = {}
    for r in results:
        if isinstance(r, Exception):
            logger.warning("Батч перевода API упал: %s", r)
            continue
        merged.update(r)
    return merged

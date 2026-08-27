"""Клиент для LanguageTool — проверка орфографии и грамматики через HTTP API."""

from __future__ import annotations

import os
import asyncio
import re
from dataclasses import dataclass

import httpx
import pymorphy3

LT_URL = os.getenv("LANGUAGETOOL_URL", "http://languagetool:8010/v2/check")
morph = pymorphy3.MorphAnalyzer()
MAX_CONCURRENT_REQUESTS = 8

SKIP_RULES = frozenset((
    "UPPERCASE_SENTENCE_START",
    "WHITESPACE_RULE",
    "DOUBLE_PUNCTUATION",
    "DotOrCase",
))

TECH_LEMMAS = frozenset((
    "api", "ddos", "ip", "url",
    "проксирование", "проксировать", "апстрим", "бэкенд", "фронтенд",
    "деплой", "деплоить", "миграция", "роллбек", "роллбэк", "хостинг",
    "редирект", "мидлвар", "эндпоинт", "пейлоад", "таймаут", "хендлер",
    "скейлинг", "балансировщик", "вебхук", "кластер", "апскейл",
    "даунтайм", "парсинг", "парсить", "сериализация", "десериализация",
    "рефакторинг", "дебаг", "медиаресурс", "терабитный", "ботнет",
    "нетарифицируемый", "высоконагруженный", "киберугроза",
    "проактивный", "проактивно",
    "пересборка", "резолвер", "логировать", "авторитативный",
    "вендор", "многовекторный",
))

TECH_PREFIXES = (
    "кибер", "мульти", "крипто", "гео", "микро", "макро",
    "нейро", "медиа", "видео", "аудио", "инфо", "теле",
)

TECH_CONTEXT_RE = (
    "api", "ddos", "dos", "dns", "tls", "http", "https", "icmp", "ipv4",
    "сервер", "протокол", "запрос", "трафик", "ботнет", "сервис",
    "атака", "пакет", "лог", "журнал", "домен", "сеть",
    "платформа", "инфраструктура", "безопасность", "финтех", "e-commerce",
)

TECH_COMPOUND_RE = re.compile(
    r"^(?:много|мульти|меж|кросс)(?:вектор|фактор|уровн|канал|поточ|узл|облач|сервис)[а-яё]*$",
    re.IGNORECASE,
)

DOMAIN_TECH_RE = re.compile(r"^[а-яё]+тех(?:а|у|ом|е|ов|ам|ами|ах)?$", re.IGNORECASE)

ALLOWED_ELLIPSIS_CASE_RE = (
    r"\b(?:больше|меньше|выше|ниже)\s+"
    r"[а-яё]+(?:ого|его)\s+"
    r"(?:протоколом|стандартом|спецификацией|регламентом)\b"
)


@dataclass
class LTIssue:
    line: int
    column: int
    end_column: int
    text: str
    rule: str
    message: str
    severity: str
    replacement: str = ""


def _is_technical_term(text: str, context: str = "") -> bool:
    normalized = text.strip(".,:;!?()[]{}«»\"'").lower()
    if not normalized:
        return False
    if normalized in TECH_LEMMAS:
        return True
    if any(ch.isdigit() for ch in normalized):
        return True
    if any(ch in normalized for ch in ("_", "/", "\\")):
        return True
    if normalized.isascii() and any(ch.isalpha() for ch in normalized):
        return True
    if any(normalized.startswith(prefix) and len(normalized) > len(prefix) + 3 for prefix in TECH_PREFIXES):
        return True
    if TECH_COMPOUND_RE.match(normalized) or DOMAIN_TECH_RE.match(normalized):
        return True
    context_lower = context.lower()
    has_tech_context = any(marker in context_lower for marker in TECH_CONTEXT_RE)
    if has_tech_context and (
        normalized.endswith(("ировать", "ироваться", "ирующий", "ируемый"))
        or normalized.endswith(("ер", "ор", "инг"))
    ):
        return True

    parses = morph.parse(normalized)
    return bool(parses and parses[0].normal_form in TECH_LEMMAS)


def _line_context(text: str, offset: int) -> str:
    start = max(text.rfind(mark, 0, offset) for mark in ".!?") + 1
    end_candidates = [pos for mark in ".!?" if (pos := text.find(mark, offset)) >= 0]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    return text[start:end].strip() or text.strip()


def _is_allowed_ellipsis_case(rule_id: str, matched_text: str, line_text: str) -> bool:
    if rule_id != "Unify_Adj_NN_case":
        return False
    if not matched_text:
        return False
    if matched_text not in line_text:
        return False
    return bool(re.search(ALLOWED_ELLIPSIS_CASE_RE, line_text.lower()))


async def run_languagetool(text: str) -> list[LTIssue]:
    """Проверяем строки параллельно, чтобы LT не склеивал контекст между блоками."""
    issues: list[LTIssue] = []

    lt_category_to_severity = {
        "TYPOS": "error",
        "SPELLING": "error",
        "GRAMMAR": "warning",
        "PUNCTUATION": "warning",
        "STYLE": "suggestion",
        "TYPOGRAPHY": "suggestion",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
            tasks = [
                _check_line(client, sem, line_num, line_text, lt_category_to_severity)
                for line_num, line_text in enumerate(text.splitlines(), 1)
                if len(line_text.strip()) >= 3
            ]
            for line_issues in await asyncio.gather(*tasks):
                issues.extend(line_issues)

    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("LT недоступен: %r", exc)

    return issues


async def _check_line(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    line_num: int,
    line_text: str,
    lt_category_to_severity: dict[str, str],
) -> list[LTIssue]:
    stripped = line_text.strip()
    leading_spaces = len(line_text) - len(line_text.lstrip())
    issues: list[LTIssue] = []

    async with sem:
        try:
            resp = await client.post(
                LT_URL,
                data={"text": stripped, "language": "ru"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

    for match in data.get("matches", []):
        rule_id = match.get("rule", {}).get("id", "UNKNOWN")
        if rule_id in SKIP_RULES:
            continue

        offset = match.get("offset", 0)
        length = match.get("length", 0)
        matched_text = stripped[offset:offset + length] if offset + length <= len(stripped) else ""

        if _is_allowed_ellipsis_case(rule_id, matched_text, stripped):
            continue
        if matched_text in {".", ",", ":", ";", "!", "?"}:
            before = stripped[offset - 1] if offset > 0 else ""
            if not before.isspace():
                continue
        if matched_text and "-" in matched_text and " " not in matched_text:
            continue
        if _is_technical_term(matched_text, stripped):
            continue

        category_id = match.get("rule", {}).get("category", {}).get("id", "")
        severity = lt_category_to_severity.get(category_id, "warning")

        replacements = match.get("replacements", [])
        replacement = replacements[0]["value"] if replacements else ""

        ctx = match.get("context", {})
        ctx_text = ctx.get("text", "")
        ctx_offset = ctx.get("offset", 0)
        ctx_length = ctx.get("length", 0)
        display_text = ctx_text[ctx_offset:ctx_offset + ctx_length] if ctx_text else matched_text
        if category_id == "PUNCTUATION":
            display_text = _line_context(stripped, offset)

        col = leading_spaces + offset + 1
        end_col = leading_spaces + offset + length + 1
        issues.append(LTIssue(
            line=line_num,
            column=col,
            end_column=end_col,
            text=display_text,
            rule=f"LanguageTool.{rule_id}",
            message=match.get("message", ""),
            severity=severity,
            replacement=replacement,
        ))

    return issues

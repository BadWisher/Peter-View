"""Запускает все движки проверки параллельно и объединяет результаты."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import regex as _regex
from dataclasses import asdict
from typing import Any

from .vale_runner import run_vale
from .lt_client import run_languagetool
from .custom_checks import run_all_custom_checks
from .style_guide_registry import get_rule

logger = logging.getLogger(__name__)

# Пользовательские паттерны исполняются на произвольном тексте, поэтому
# ограничиваем и длину, и время: катастрофический бэктрекинг не должен
# подвешивать воркер целиком.
USER_REGEX_MAX_LENGTH = 500
USER_REGEX_TIMEOUT_MS = int(os.getenv("USER_REGEX_TIMEOUT_MS", "200"))


def _safe_regex(pattern: str):
    """Компилирует пользовательский паттерн; таймаут передаётся на исполнение."""
    return _regex.compile(pattern, _regex.IGNORECASE)


async def check_text(
    text: str,
    user_rules: list[dict[str, str]] | None = None,
    include_spelling: bool = True,
) -> list[dict[str, Any]]:
    """Vale + кастомные проверки + LT параллельно, на выходе единый список."""

    vale_task = asyncio.create_task(run_vale(text))
    lt_task = asyncio.create_task(run_languagetool(text)) if include_spelling else None

    loop = asyncio.get_running_loop()
    custom_task = loop.run_in_executor(None, run_all_custom_checks, text)

    tasks = [vale_task, custom_task]
    if lt_task is not None:
        tasks.append(lt_task)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    vale_issues = results[0]
    custom_issues = results[1]
    lt_issues = results[2] if lt_task is not None else []

    unified: list[dict[str, Any]] = []

    if isinstance(vale_issues, list):
        for i in vale_issues:
            unified.append(_enrich_issue(asdict(i), "style-guide"))

    if isinstance(custom_issues, list):
        for i in custom_issues:
            unified.append(_enrich_issue(asdict(i), "style-guide"))

    if isinstance(lt_issues, list):
        for i in lt_issues:
            unified.append(_enrich_issue(asdict(i), "spelling", registry_id="LanguageTool.ru"))

    if user_rules:
        unified.extend(_enrich_issue(issue, "custom") for issue in _apply_user_rules(text, user_rules))

    unified = _deduplicate_issues(unified)
    unified.sort(key=lambda x: (x.get("line", 0), x.get("column", 0)))
    return unified


def _deduplicate_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_style_guide_fragments = {
        (
            issue.get("line", 0),
            issue.get("column", 0),
            str(issue.get("text", "")).lower(),
        )
        for issue in issues
        if issue.get("source") == "style-guide"
    }

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str, str]] = set()
    for issue in issues:
        text = str(issue.get("text", "")).lower()
        fragment_key = (issue.get("line", 0), issue.get("column", 0), text)
        if issue.get("source") == "spelling" and fragment_key in seen_style_guide_fragments:
            continue

        exact_key = (
            issue.get("line", 0),
            issue.get("column", 0),
            text,
            issue.get("registry_id") or issue.get("rule", ""),
        )
        if exact_key in seen:
            continue
        seen.add(exact_key)
        deduped.append(issue)
    return deduped


def _enrich_issue(
    issue: dict[str, Any],
    source: str,
    registry_id: str | None = None,
) -> dict[str, Any]:
    rule_id = registry_id or issue.get("rule", "")
    rule = get_rule(rule_id)
    issue["source"] = source
    if rule:
        issue["registry_id"] = rule["id"]
        issue["guide_section"] = rule["section"]
        issue["rule_name"] = rule["name"]
        issue["automation"] = rule["automation"]
        issue["rule_group"] = rule["group"]
    elif source == "custom":
        issue["registry_id"] = "UserRule"
        issue["guide_section"] = "Пользовательские правила"
        issue["rule_name"] = "Пользовательское правило"
        issue["automation"] = "automatic"
        issue["rule_group"] = "Пользовательские правила"
    return issue


def _apply_user_rules(text: str, rules: list[dict[str, str]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    lines = text.split("\n")

    for rule in rules:
        pattern = rule.get("pattern", "")
        message = rule.get("message", f'Найдено: "{pattern}"')
        severity = rule.get("severity", "warning")
        if not pattern or len(pattern) > USER_REGEX_MAX_LENGTH:
            continue
        try:
            regex = _safe_regex(pattern)
        except re.error:
            continue

        for line_num, line_text in enumerate(lines, 1):
            try:
                matches = list(regex.finditer(line_text, timeout=USER_REGEX_TIMEOUT_MS / 1000))
            except TimeoutError:
                logger.warning(
                    "Пользовательский паттерн превышает таймаут %dмс и пропущен: %.80s",
                    USER_REGEX_TIMEOUT_MS, pattern,
                )
                break
            for m in matches:
                issues.append({
                    "line": line_num,
                    "column": m.start() + 1,
                    "end_column": m.end() + 1,
                    "text": m.group(),
                    "rule": "UserRule",
                    "message": message,
                    "severity": severity,
                    "replacement": "",
                })
    return issues

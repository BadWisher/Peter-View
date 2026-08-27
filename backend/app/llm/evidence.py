"""Детерминированные сигналы для пайплайна вычитки.

Модуль не кодирует частные примеры. Он преобразует результаты уже существующих
движков и лексикона выбранного гайда в общий формат кандидатов, привязанный к
блокам документа. Неоднозначные сигналы затем проверяет LLM-верификатор.
"""

from __future__ import annotations

import re
from typing import Any

from ..checker import check_text
from .documents import Document
from .styleguide import StyleGuide


def _engine_text(document: Document) -> tuple[str, dict[int, int]]:
    """Возвращает по одной строке на блок и отображение line -> block_index."""
    lines: list[str] = []
    line_to_block: dict[int, int] = {}
    for line_number, block in enumerate(document.blocks, 1):
        normalized = " ".join(block.plain.split())
        lines.append(normalized)
        line_to_block[line_number] = block.index
    return "\n".join(lines), line_to_block


def _severity(value: str) -> str:
    if value == "error":
        return "blocker"
    if value == "suggestion":
        return "minor"
    return "suggestion"


async def collect_engine_evidence(document: Document, guide: StyleGuide) -> list[dict[str, Any]]:
    """Запускает существующий движок и возвращает привязанные к гайду кандидаты."""
    text, line_to_block = _engine_text(document)
    if not text.strip():
        return []

    issues = await check_text(text, include_spelling=True)
    candidates: list[dict[str, Any]] = []
    for issue in issues:
        registry_id = str(issue.get("registry_id") or issue.get("rule") or "")
        rule_id = registry_id
        evidence_source = str(issue.get("source") or "engine")

        if registry_id == "LanguageTool.ru":
            rule_id = "Базовая.Орфография"
        if rule_id not in guide.effective_ids:
            continue

        try:
            line = int(issue.get("line", 0))
        except (TypeError, ValueError):
            continue
        block_index = line_to_block.get(line)
        if block_index is None:
            continue

        rule = guide.get_rule(rule_id) or {}
        objective = bool(rule.get("machine_verifiable", False))
        candidates.append({
            "block_index": block_index,
            "type": str(issue.get("rule_group") or "style"),
            "severity": _severity(str(issue.get("severity") or "warning")),
            "rule_id": rule_id,
            "reasoning": str(issue.get("message") or ""),
            "description": str(issue.get("message") or rule.get("title") or rule_id),
            "suggestion": str(issue.get("replacement") or ""),
            "span_text": str(issue.get("text") or ""),
            "source_workers": [0],
            "evidence_source": evidence_source,
            "verification_required": not objective,
        })
    return candidates


def collect_lexicon_evidence(document: Document, guide: StyleGuide) -> list[dict[str, Any]]:
    """Находит точные лексиконные совпадения; контекст остаётся за верификатором."""
    candidates: list[dict[str, Any]] = []
    for entry in guide.lexicon_forbidden:
        term = str(entry.get("term") or "").strip()
        rule_id = str(entry.get("rule_id") or "").strip()
        if not term or not rule_id:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        for block in document.blocks:
            for match in pattern.finditer(block.plain):
                candidates.append({
                    "block_index": block.index,
                    "type": "terminology",
                    "severity": "suggestion",
                    "rule_id": rule_id,
                    "reasoning": str(entry.get("comment") or ""),
                    "description": f"Проверьте употребление выражения «{match.group()}».",
                    "suggestion": str(entry.get("replacement") or ""),
                    "span_text": match.group(),
                    "source_workers": [8],
                    "evidence_source": "lexicon",
                    "verification_required": True,
                })
    return candidates

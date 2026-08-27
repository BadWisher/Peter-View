"""Модели замечаний и валидация ответов воркеров.

Главный фильтр против галлюцинаций: замечание без rule_id из текущего стайл-гайда
не засчитывается. Severity модели (blocker/suggestion/minor) маппится в severity UI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .styleguide import StyleGuide

logger = logging.getLogger(__name__)

LLM_SEVERITIES = {"blocker", "suggestion", "minor"}
SEVERITY_TO_UI = {"blocker": "error", "suggestion": "warning", "minor": "suggestion"}


def _clean_issue(
    raw: dict,
    source_worker: int,
    valid_ids: set[str],
    valid_indices: set[int] | None = None,
    blocks_by_index: dict[int, str] | None = None,
    guide: "StyleGuide | None" = None,
) -> dict | None:
    if not isinstance(raw, dict):
        return None

    rule_id = str(raw.get("rule_id", "")).strip()
    if not rule_id or rule_id not in valid_ids:
        return None

    severity = str(raw.get("severity", "")).strip().lower()
    if severity not in LLM_SEVERITIES:
        severity = "suggestion"

    try:
        block_index = int(raw["block_index"])
    except (TypeError, ValueError):
        return None
    except KeyError:
        return None
    if valid_indices is not None and block_index not in valid_indices:
        return None

    description = str(raw.get("description", "")).strip()
    if not description:
        return None

    suggestion = str(raw.get("suggestion", "")).strip()
    span_text = str(raw.get("span_text", "")).strip()
    source_text = (blocks_by_index or {}).get(block_index, "")
    if span_text and source_text and span_text not in source_text:
        return None
    if suggestion and (
        (source_text and suggestion.strip() == source_text.strip())
        or (span_text and suggestion.strip() == span_text.strip())
    ):
        return None

    if guide is not None and suggestion:
        rule = guide.get_rule(rule_id) or {}
        constraints = rule.get("constraints") if isinstance(rule.get("constraints"), dict) else {}
        forbidden = constraints.get("forbidden_chars", rule.get("forbidden_chars", [])) or []
        forbidden_introduced = constraints.get("forbidden_introduced_chars", []) or []
        required = constraints.get("required_chars", rule.get("required_chars", [])) or []
        if any(str(char) in suggestion for char in forbidden):
            return None
        constraint_source = span_text or source_text
        if any(
            str(char) in suggestion and str(char) not in constraint_source
            for char in forbidden_introduced
        ):
            return None
        if required and not any(str(char) in suggestion for char in required):
            return None

    return {
        "block_index": block_index,
        "type": str(raw.get("type", "")).strip() or "style",
        "severity": severity,
        "rule_id": rule_id,
        "reasoning": str(raw.get("reasoning", "")).strip(),
        "description": description,
        "suggestion": suggestion,
        "span_text": span_text,
        "source_workers": [source_worker],
        "evidence_source": str(raw.get("evidence_source", "llm")),
        "verification_status": str(raw.get("verification_status", "candidate")),
    }


def parse_worker_issues(
    response: dict,
    source_worker: int,
    valid_ids: set[str],
    *,
    valid_indices: set[int] | None = None,
    blocks_by_index: dict[int, str] | None = None,
    guide: "StyleGuide | None" = None,
) -> list[dict]:
    """Достаёт валидные замечания из ответа воркера, отбрасывая галлюцинации."""
    if not isinstance(response, dict):
        return []
    issues = response.get("issues", [])
    if not isinstance(issues, list):
        return []

    cleaned = []
    for raw in issues:
        issue = _clean_issue(
            raw,
            source_worker,
            valid_ids,
            valid_indices=valid_indices,
            blocks_by_index=blocks_by_index,
            guide=guide,
        )
        if issue:
            cleaned.append(issue)
    dropped = len(issues) - len(cleaned)
    if dropped:
        logger.info("Воркер %d: отброшено %d замечаний без валидного rule_id", source_worker, dropped)
    return cleaned


def validate_final_issues(
    issues: list[dict],
    guide: "StyleGuide",
    blocks_by_index: dict[int, str],
) -> tuple[list[dict], list[dict]]:
    """Проверяет итог без потери происхождения и возвращает причины отсева."""
    accepted: list[dict] = []
    rejected: list[dict] = []
    valid_indices = set(blocks_by_index)
    for issue in issues:
        cleaned = _clean_issue(
            issue,
            source_worker=6,
            valid_ids=guide.effective_ids,
            valid_indices=valid_indices,
            blocks_by_index=blocks_by_index,
            guide=guide,
        )
        if cleaned is None:
            rejected.append({
                "rule_id": issue.get("rule_id"),
                "block_index": issue.get("block_index"),
                "reason": "invalid_reference_or_constraint",
            })
            continue
        cleaned["source_workers"] = issue.get("source_workers", cleaned["source_workers"])
        cleaned["evidence_source"] = issue.get("evidence_source", cleaned["evidence_source"])
        cleaned["verification_status"] = issue.get(
            "verification_status", cleaned["verification_status"]
        )
        accepted.append(cleaned)
    return accepted, rejected


def summarize(issues: list[dict]) -> dict:
    return {
        "blocker": sum(1 for i in issues if i.get("severity") == "blocker"),
        "suggestion": sum(1 for i in issues if i.get("severity") == "suggestion"),
        "minor": sum(1 for i in issues if i.get("severity") == "minor"),
    }


def to_ui_issue(issue: dict, blocks_by_index: dict[int, str]) -> dict:
    """Приводит замечание LLM к формату строки таблицы существующего UI."""
    block_index = issue.get("block_index", 0)
    description = issue.get("description", "")
    reasoning = issue.get("reasoning", "")
    message = description
    if reasoning:
        message = f"{description}\n\nОбоснование: {reasoning}"

    return {
        "line": block_index,
        "text": blocks_by_index.get(block_index, ""),
        "severity": SEVERITY_TO_UI.get(issue.get("severity"), "suggestion"),
        "message": message,
        "replacement": issue.get("suggestion", ""),
        "rule": issue.get("rule_id", ""),
        "source": "llm",
        "rule_group": issue.get("type", ""),
        "page_url": "",
    }

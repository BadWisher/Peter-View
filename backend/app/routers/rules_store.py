from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi import HTTPException

from .infra import RULES_FILE, RULE_SEVERITIES, _rules_lock
from ..style_guide_registry import get_registry

def _parse_user_rules(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _read_rules() -> list[dict[str, str]]:
    with _rules_lock:
        if not RULES_FILE.exists():
            return []
        try:
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []


def _write_rules(rules: list[dict[str, str]]) -> None:
    with _rules_lock:
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        RULES_FILE.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _normalize_rule(rule: dict[str, Any], rule_id: str | None = None) -> dict[str, str]:
    pattern = str(rule.get("pattern", "")).strip()
    message = str(rule.get("message", "")).strip()
    severity = str(rule.get("severity", "warning")).strip()

    if not pattern:
        raise HTTPException(400, "Укажи текст или регулярное выражение")
    if severity not in RULE_SEVERITIES:
        raise HTTPException(400, "Неверный тип правила")
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise HTTPException(400, f"Неверное регулярное выражение: {e}")

    return {
        "id": rule_id or str(uuid.uuid4()),
        "pattern": pattern,
        "message": message or f'Найдено: "{pattern}"',
        "severity": severity,
    }


def _rules_for_check(raw_user_rules: str = "") -> list[dict[str, str]]:
    rules = _read_rules()
    for rule in _parse_user_rules(raw_user_rules):
        try:
            rules.append(_normalize_rule(rule))
        except HTTPException:
            continue
    return rules


def _read_builtin_rules() -> list[dict[str, Any]]:
    return get_registry(include_spelling=True)

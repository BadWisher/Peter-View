from __future__ import annotations

from typing import Any

from ..checker import check_text
from .infra import CHUNK_LINES, _check_sem
from .rules_store import _rules_for_check

async def _check_text_chunked(text: str, user_rules=None, include_spelling=True) -> list[dict]:
    """Разбивает длинный текст на чанки, проверяет каждый, склеивает результат."""
    lines = text.split("\n")
    if len(lines) <= CHUNK_LINES:
        async with _check_sem:
            return await check_text(text, user_rules=user_rules, include_spelling=include_spelling)

    all_issues: list[dict] = []
    for start in range(0, len(lines), CHUNK_LINES):
        chunk = "\n".join(lines[start:start + CHUNK_LINES])
        async with _check_sem:
            issues = await check_text(chunk, user_rules=user_rules, include_spelling=include_spelling)
        for issue in issues:
            issue["line"] = issue.get("line", 0) + start
        all_issues.extend(issues)
    return all_issues

def _summary(issues: list[dict]) -> dict:
    return {
        "total": len(issues),
        "errors": sum(1 for i in issues if i.get("severity") == "error"),
        "warnings": sum(1 for i in issues if i.get("severity") == "warning"),
        "suggestions": sum(1 for i in issues if i.get("severity") == "suggestion"),
    }

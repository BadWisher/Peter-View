from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_user
from ..llm import stats as llm_stats
from ..llm import styleguide_store

router = APIRouter(tags=["История"])

def _rule_titles() -> dict[str, str]:
    """rule_id → человекочитаемый заголовок правила из всех сохранённых гайдов."""
    from ..llm import styleguide as _sg
    titles: dict[str, str] = {r["rule_id"]: r["title"] for r in _sg.BASE_RULES}
    for guide in styleguide_store.list_guides():
        for rule in guide.rules:
            rid = str(rule.get("rule_id", "")).strip()
            title = str(rule.get("title", "")).strip()
            if rid and title:
                titles.setdefault(rid, title)
        for entry in guide.lexicon_forbidden:
            rid = str(entry.get("rule_id", "")).strip()
            term = str(entry.get("term", "")).strip()
            if rid and term:
                titles.setdefault(rid, f"Запрещено: «{term}»")
    return titles


@router.get("/api/checks/top-rules")
async def checks_top_rules(_user: str = Depends(require_user)):
    data = llm_stats.top_rules_by_user()
    titles = _rule_titles()
    for user in data.get("users", []):
        for rule in user.get("rules", []):
            rule["title"] = titles.get(rule["rule_id"], "")
    return data


# --- Состояние системы ------------------------------------------------------

@router.get("/api/checks/insights")
async def checks_insights(_user: str = Depends(require_user)):
    data = llm_stats.top_rules_by_user()
    titles = _rule_titles()
    for user in data.get("users", []):
        for rule in user.get("rules", []):
            rule["title"] = titles.get(rule["rule_id"], "")
    return {**data, "tokens": llm_stats.token_totals()}

@router.get("/api/checks/history")
async def checks_history(user: str = Depends(require_user), limit: int = 10, offset: int = 0):
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    items = llm_stats.recent_history(user, limit=limit, offset=offset)
    total = llm_stats.history_count(user)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/api/checks/history/{history_id}")
async def checks_history_report(history_id: int, user: str = Depends(require_user)):
    report = llm_stats.history_report(user, history_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    return report

from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
from ..auth import require_admin, require_user
from .rules_store import _normalize_rule, _read_builtin_rules, _read_rules, _write_rules

router = APIRouter(tags=["Правила"])

class RuleRequest(BaseModel):
    pattern: str
    message: str = ""
    severity: str = "warning"


@router.get("/api/rules")
async def list_rules(_user: str = Depends(require_user)):
    return {"rules": _read_rules()}


@router.get("/api/rules/builtin")
async def list_builtin_rules(_user: str = Depends(require_user)):
    return {"rules": _read_builtin_rules()}


@router.post("/api/rules")
async def create_rule(body: RuleRequest, _user: str = Depends(require_admin)):
    rules = _read_rules()
    rule = _normalize_rule(body.dict())
    rules.append(rule)
    _write_rules(rules)
    return rule


@router.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: str, _user: str = Depends(require_admin)):
    rules = _read_rules()
    kept = [rule for rule in rules if rule.get("id") != rule_id]
    if len(kept) == len(rules):
        raise HTTPException(404, "Правило не найдено")
    _write_rules(kept)
    return {"ok": True}

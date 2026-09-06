from __future__ import annotations

import asyncio
import shutil
from typing import Any

from fastapi import APIRouter, Depends

from .. import audit, backups, features
from .. import oidc as oidc_login
from ..auth import require_admin
from ..llm import client as llm_client
from ..llm import rag as llm_rag
from ..llm import repo_store
from ..llm import stats as llm_stats
from .infra import DATA_DIR
from .infra import DOCS_ENABLED

router = APIRouter(tags=["Служебное"])

@router.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/api/config")
async def public_config():
    return {
        "version": "0.1.0",
        "features": features.snapshot(),
        "oidc": oidc_login.configured(),
        "docs": DOCS_ENABLED,
    }


@router.get("/api")
async def api_root():
    payload = {"name": "Peter View API", "version": "0.1.0"}
    if DOCS_ENABLED:
        payload.update({"docs": "/api/docs", "redoc": "/api/redoc", "openapi": "/api/openapi.json"})
    return payload

@router.get("/api/health/full")
async def health_full(_user: str = Depends(require_admin)):
    result: dict[str, Any] = {}
    try:
        await asyncio.wait_for(llm_client.healthcheck(), timeout=20)
        result["llm"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["llm"] = {"ok": False, "error": str(e)}
    try:
        await asyncio.wait_for(asyncio.to_thread(llm_rag.healthcheck), timeout=20)
        result["embedding"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["embedding"] = {"ok": False, "error": str(e)}

    import shutil
    try:
        du = shutil.disk_usage(str(DATA_DIR))
        result["disk"] = {"total": du.total, "used": du.used, "free": du.free}
    except OSError as e:
        result["disk"] = {"error": str(e)}

    result["tokens"] = llm_stats.token_totals()
    result["backup"] = backups.last_snapshot()
    result["repo"] = repo_store.usage()
    result["audit"] = audit.recent(80)
    return result


# --- Репозиторий документов на вычитку --------------------------------------

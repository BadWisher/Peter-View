from __future__ import annotations

import os

from fastapi import HTTPException

OPTIONAL = ("documents", "api", "watch", "screenshots")
_TRUE = {"1", "true", "yes", "on", "да"}

_ENV = {
    "documents": "FEATURE_DOCUMENTS",
    "api": "FEATURE_API",
    "watch": "FEATURE_WATCH",
    "screenshots": "FEATURE_SCREENSHOTS",
}


def enabled(name: str) -> bool:
    env = _ENV.get(name)
    if not env:
        return True
    raw = os.getenv(env, "false")
    return str(raw).strip().lower() in _TRUE


def snapshot() -> dict[str, bool]:
    return {name: enabled(name) for name in OPTIONAL}


def require_feature(name: str):
    def dep() -> None:
        if not enabled(name):
            raise HTTPException(404, "Раздел недоступен")

    return dep

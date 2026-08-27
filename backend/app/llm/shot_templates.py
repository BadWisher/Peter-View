"""Общие шаблоны размеров для раздела «Скриншоты».

Список шаблонов (имя + ширина в пикселях) хранится в data/screenshot_templates.json
и применяется ко всем пользователям (как «Настройки проверки»). При первом обращении файл
создаётся с парой типовых ширин.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TEMPLATES_FILE = DATA_DIR / "screenshot_templates.json"

MIN_WIDTH = 50
MAX_WIDTH = 4000

_DEFAULTS: list[dict[str, Any]] = [
    {"id": "narrow", "name": "Узкий (документация)", "width": 800},
    {"id": "wide", "name": "Широкий", "width": 1200},
]

_lock = threading.Lock()
_cache: list[dict[str, Any]] | None = None


def _normalize(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    tid = str(item.get("id") or "").strip() or uuid.uuid4().hex[:8]
    name = str(item.get("name") or "").strip()
    try:
        width = int(item.get("width"))
    except (TypeError, ValueError):
        return None
    if not name or not (MIN_WIDTH <= width <= MAX_WIDTH):
        return None
    return {"id": tid, "name": name, "width": width}


def _load() -> list[dict[str, Any]]:
    if TEMPLATES_FILE.exists():
        try:
            saved = json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, list):
                out = [t for t in (_normalize(x) for x in saved) if t]
                return out
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Не удалось прочитать %s: %s", TEMPLATES_FILE, e)
    return [dict(t) for t in _DEFAULTS]


def _save(items: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_templates() -> list[dict[str, Any]]:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load()
        return [dict(t) for t in _cache]


def add_template(name: str, width: int) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Укажи название шаблона")
    try:
        width = int(width)
    except (TypeError, ValueError):
        raise ValueError("Ширина должна быть числом")
    if not (MIN_WIDTH <= width <= MAX_WIDTH):
        raise ValueError(f"Ширина должна быть от {MIN_WIDTH} до {MAX_WIDTH} px")

    global _cache
    with _lock:
        items = _cache if _cache is not None else _load()
        template = {"id": uuid.uuid4().hex[:8], "name": name, "width": width}
        items = items + [template]
        _save(items)
        _cache = items
        return dict(template)


def delete_template(template_id: str) -> None:
    global _cache
    with _lock:
        items = _cache if _cache is not None else _load()
        filtered = [t for t in items if t["id"] != template_id]
        if len(filtered) == len(items):
            raise KeyError(template_id)
        _save(filtered)
        _cache = filtered

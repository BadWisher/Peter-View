"""Настройки LLM. Пустой URL значит полную проверку не вызывать."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
SETTINGS_FILE = DATA_DIR / "llm_settings.json"

# Поля настроек: ключ -> (тип, env-переменная, значение по умолчанию)
SPEC: dict[str, tuple[type, str, Any]] = {
    "llm_base_url": (str, "LLM_BASE_URL", ""),
    "llm_api_key": (str, "LLM_API_KEY", ""),
    "llm_model": (str, "LLM_MODEL", ""),
    "llm_temperature": (float, "LLM_TEMPERATURE", 0.0),
    "llm_concurrency": (int, "LLM_CONCURRENCY", 5),
    "llm_timeout": (float, "LLM_TIMEOUT", 120.0),
    "llm_json_mode": (bool, "LLM_JSON_MODE", True),
    "llm_reasoning_effort": (str, "LLM_REASONING_EFFORT", ""),
    "embedding_base_url": (str, "EMBEDDING_BASE_URL", ""),
    "embedding_api_key": (str, "EMBEDDING_API_KEY", ""),
    "embedding_model": (str, "EMBEDDING_MODEL", ""),
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_listeners: list[Callable[[], None]] = []

# Секретные поля: наружу не отдаём, пустым значением не затираем.
SECRET_FIELDS = {"llm_api_key", "embedding_api_key"}

# URL-поля: проверяем схему перед сохранением (сервер сам ходит на эти адреса
# с API-ключом, поэтому мусорная/нестандартная схема недопустима).
URL_FIELDS = {"llm_base_url", "embedding_base_url"}


def _validate_base_url(field: str, value: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{field}: адрес должен начинаться с http:// или https://")


_TRUE_STRINGS = {"1", "true", "yes", "on", "да"}


def _coerce(field: str, value: Any) -> Any:
    typ = SPEC[field][0]
    try:
        if typ is bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in _TRUE_STRINGS
        return typ(value)
    except (TypeError, ValueError):
        return SPEC[field][2]


def _defaults() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, (typ, env, default) in SPEC.items():
        raw = os.getenv(env)
        out[field] = _coerce(field, raw) if raw not in (None, "") else default
    return out


def _load() -> dict[str, Any]:
    cfg = _defaults()
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for field in SPEC:
                    if field in saved:
                        cfg[field] = _coerce(field, saved[field])
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Не удалось прочитать %s: %s", SETTINGS_FILE, e)
    return cfg


def get() -> dict[str, Any]:
    """Текущие настройки (с кэшированием)."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load()
        return dict(_cache)


def get_value(field: str) -> Any:
    return get()[field]


def get_masked() -> dict[str, Any]:
    """Настройки для выдачи на фронт: секреты скрыты, добавлены флаги *_set."""
    cfg = get()
    out = dict(cfg)
    for field in SECRET_FIELDS:
        out[f"{field}_set"] = bool(str(cfg.get(field, "")).strip())
        out[field] = ""
    return out


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Обновляет настройки. Пустые значения секретных полей не затирают сохранённое."""
    global _cache
    with _lock:
        current = _cache if _cache is not None else _load()
        merged = dict(current)
        for field in SPEC:
            if field not in patch:
                continue
            value = patch[field]
            if field in SECRET_FIELDS and (value is None or str(value).strip() == ""):
                continue
            if field in URL_FIELDS and str(value).strip():
                _validate_base_url(field, str(value).strip())
            merged[field] = _coerce(field, value)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Файл содержит API-ключи: restrictive umask для новых файлов и chmod
        # для уже существующего (write_text права не меняет).
        umask = os.umask(0o077)
        try:
            SETTINGS_FILE.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        finally:
            os.umask(umask)
        os.chmod(SETTINGS_FILE, 0o600)
        _cache = merged

    for listener in list(_listeners):
        try:
            listener()
        except Exception as e:  # noqa: BLE001
            logger.warning("Подписчик на смену настроек упал: %s", e)
    logger.info("Настройки LLM обновлены (модель=%s)", merged.get("llm_model"))
    return dict(merged)


def register_listener(callback: Callable[[], None]) -> None:
    """Подписка на смену настроек (для сброса кэшированных клиентов)."""
    _listeners.append(callback)

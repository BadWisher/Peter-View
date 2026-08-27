"""Файловое хранилище стайл-гайдов.

Каждый гайд — отдельный YAML-файл в data/styleguides/<id>.yaml (том backend-data,
поэтому переживает пересборку). Общий пул: гайды видны всем пользователям.
Встроенный гайд «Базовый» сидится из styleguide/rules.yaml и не удаляется.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
import uuid
from pathlib import Path

import yaml

from .styleguide import BASE_IDS, DEFAULT_RULE_METADATA, StyleGuide

logger = logging.getLogger(__name__)

STORE_DIR = Path(os.getenv("STYLEGUIDE_STORE_DIR", "/app/data/styleguides"))
DEFAULT_RULES_PATH = Path(os.getenv("STYLEGUIDE_PATH", "/app/styleguide/rules.yaml"))
DEFAULT_ID = "default"
DEFAULT_NAME = "Базовый (РУ Style Guide)"

_RULE_FIELDS = (
    "section", "group", "rule", "generalization", "severity",
    "good_examples", "bad_examples", "categories", "tasks", "scope",
    "priority", "mandatory", "machine_verifiable", "relationships", "constraints",
    "conflict_family",
)

_RELATIONSHIP_FIELDS = ("requires", "conflicts", "supersedes", "specializes", "related")

_lock = threading.RLock()


def _ensure_dir() -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)


# id гайда — это "default" либо uuid4().hex[:12]. Ограничиваем набор символов,
# чтобы guide_id из URL нельзя было использовать для path traversal.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe_id(guide_id: str) -> str:
    if not isinstance(guide_id, str) or not _ID_RE.fullmatch(guide_id):
        raise ValueError(f"Недопустимый идентификатор гайда: {guide_id!r}")
    return guide_id


def _path(guide_id: str) -> Path:
    return STORE_DIR / f"{_safe_id(guide_id)}.yaml"


def _hash_rules(rules: list[dict]) -> str:
    payload = json.dumps(rules, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _boolean(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0", ""}:
            return False
    return default if value is None else bool(value)


def _metadata(raw: dict) -> dict:
    relationships = raw.get("relationships") or {}
    if not isinstance(relationships, dict):
        relationships = {}
    normalized_relationships: dict[str, list[str]] = {}
    for name in _RELATIONSHIP_FIELDS:
        values = _string_list(relationships.get(name))
        if values:
            normalized_relationships[name] = values
    try:
        priority = max(0, min(100, int(raw.get("priority", DEFAULT_RULE_METADATA["priority"]))))
    except (TypeError, ValueError):
        priority = DEFAULT_RULE_METADATA["priority"]
    constraints = raw.get("constraints") or {}
    if not isinstance(constraints, dict):
        constraints = {}
    normalized_constraints = {
        name: _string_list(constraints.get(name))
        for name in ("forbidden_chars", "forbidden_introduced_chars", "required_chars")
        if _string_list(constraints.get(name))
    }
    return {
        "categories": _string_list(raw.get("categories")),
        "tasks": _string_list(raw.get("tasks")),
        "scope": str(raw.get("scope") or DEFAULT_RULE_METADATA["scope"]).strip().lower(),
        "priority": priority,
        "mandatory": _boolean(
            raw.get("mandatory"), DEFAULT_RULE_METADATA["mandatory"],
        ),
        "machine_verifiable": _boolean(
            raw.get("machine_verifiable"), DEFAULT_RULE_METADATA["machine_verifiable"],
        ),
        "relationships": normalized_relationships,
        "constraints": normalized_constraints,
        "conflict_family": str(raw.get("conflict_family") or "").strip(),
    }


def _slugify(text: str) -> str:
    # NFC (а не NFKD): сохраняет цельные кириллические буквы. NFKD раскладывал
    # «й»→«и»+breve и «ё»→«е»+diaeresis, а комбинирующие знаки потом срезались
    # как не-\w, превращая «нейтральный» в «неи_тральныи».
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[^\w]+", "_", text, flags=re.UNICODE).strip("_")
    return text[:40] or "rule"


def validate_rules(rules: list) -> list[dict]:
    """Приводит правила к каноничному виду: непустой title/rule, уникальный rule_id.

    rule_id генерируется автоматически из title, если не задан или повторяется,
    чтобы валидация замечаний по rule_id оставалась надёжной.
    """
    if not isinstance(rules, list):
        raise ValueError("rules должны быть списком")

    cleaned: list[dict] = []
    seen_ids: set[str] = set()

    for raw in rules:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        rule_text = str(raw.get("rule", "")).strip()
        if not title and not rule_text:
            continue
        if not title:
            title = rule_text[:60]

        rule_id = str(raw.get("rule_id", "")).strip()
        if not rule_id or rule_id in seen_ids:
            base = rule_id or f"Custom.{_slugify(title)}"
            candidate = base
            n = 2
            while candidate in seen_ids:
                candidate = f"{base}_{n}"
                n += 1
            rule_id = candidate
        seen_ids.add(rule_id)

        metadata = _metadata(raw)
        inferred: list[str] = []
        if not metadata["categories"]:
            section_root = str(raw.get("section") or raw.get("group") or "").split(" / ")[0]
            if section_root:
                metadata["categories"] = [section_root]
                inferred.append("categories")
        if not metadata["tasks"]:
            metadata["tasks"] = ["proofreading"]
            inferred.append("tasks")
        rule: dict = {"rule_id": rule_id, "title": title, **metadata}
        if inferred:
            rule["metadata_inferred"] = inferred
        if rule_text:
            rule["rule"] = rule_text
        for field_name in _RULE_FIELDS:
            value = raw.get(field_name)
            if value in (None, "", [], {}):
                continue
            if field_name in (
                "categories", "tasks", "scope", "priority", "mandatory",
                "machine_verifiable", "relationships",
                "constraints",
                "conflict_family",
            ):
                continue
            if field_name in ("good_examples", "bad_examples"):
                if isinstance(value, list):
                    items = [str(v).strip() for v in value if str(v).strip()]
                    if items:
                        rule[field_name] = items
                continue
            rule[field_name] = str(value).strip() if not isinstance(value, str) else value.strip()
        cleaned.append(rule)

    if not cleaned:
        raise ValueError("После валидации не осталось ни одного правила")
    _validate_rule_relationships(cleaned)
    return cleaned


def _validate_rule_relationships(rules: list[dict]) -> None:
    """Отсекает структурные противоречия в связях правил, которые видно уже при сохранении."""
    ids = {rule["rule_id"] for rule in rules} | BASE_IDS
    supersedes = {
        rule["rule_id"]: set((rule.get("relationships") or {}).get("supersedes", []))
        for rule in rules
    }
    for rule in rules:
        rule_id = rule["rule_id"]
        relationships = rule.get("relationships") or {}
        if rule_id in relationships.get("conflicts", []):
            raise ValueError(f"{rule_id}: правило не может конфликтовать само с собой")
        unknown_authority = (
            set(relationships.get("supersedes", []))
            | set(relationships.get("specializes", []))
            | set(relationships.get("requires", []))
        ) - ids
        if unknown_authority:
            raise ValueError(
                f"{rule_id}: неизвестные связанные правила: {sorted(unknown_authority)}"
            )

    def visit(rule_id: str, path: set[str]) -> None:
        if rule_id in path:
            raise ValueError(f"Цикл supersedes с участием {rule_id}")
        for target in supersedes.get(rule_id, set()):
            if target in supersedes:
                visit(target, path | {rule_id})

    for rule_id in supersedes:
        visit(rule_id, set())

    families: dict[str, list[dict]] = {}
    for rule in rules:
        family = str(rule.get("conflict_family") or "")
        if family:
            families.setdefault(family, []).append(rule)
    for family, family_rules in families.items():
        good: dict[str, str] = {}
        bad: dict[str, str] = {}
        for rule in family_rules:
            for example in rule.get("good_examples", []) or []:
                good.setdefault(str(example).strip(), rule["rule_id"])
            for example in rule.get("bad_examples", []) or []:
                bad.setdefault(str(example).strip(), rule["rule_id"])
        overlap = set(good) & set(bad)
        if overlap:
            example = sorted(overlap)[0]
            raise ValueError(
                f"Конфликт семейства {family}: пример одновременно хороший и плохой: {example}"
            )


_LEXICON_PREFIX = "Lexicon."


def validate_lexicon(lexicon) -> dict:
    """Приводит лексикон к каноничному виду: непустой term, уникальный rule_id у запрещённых.

    rule_id запрещённого выражения генерируется из term (с префиксом Lexicon.), если не
    задан или повторяется, чтобы валидация замечаний по rule_id оставалась надёжной.
    """
    if not lexicon:
        return {"forbidden": [], "allowed": []}
    if not isinstance(lexicon, dict):
        raise ValueError("lexicon должен быть объектом с полями forbidden/allowed")

    seen_ids: set[str] = set()
    forbidden: list[dict] = []
    for raw in lexicon.get("forbidden", []) or []:
        if not isinstance(raw, dict):
            continue
        term = str(raw.get("term", "")).strip()
        if not term:
            continue
        rule_id = str(raw.get("rule_id", "")).strip()
        if not rule_id or not rule_id.startswith(_LEXICON_PREFIX) or rule_id in seen_ids:
            base = f"{_LEXICON_PREFIX}{_slugify(term)}"
            candidate = base
            n = 2
            while candidate in seen_ids:
                candidate = f"{base}_{n}"
                n += 1
            rule_id = candidate
        seen_ids.add(rule_id)
        entry: dict = {"rule_id": rule_id, "term": term}
        for f in ("replacement", "en", "comment"):
            value = str(raw.get(f, "")).strip()
            if value:
                entry[f] = value
        forbidden.append(entry)

    allowed: list[dict] = []
    for raw in lexicon.get("allowed", []) or []:
        if not isinstance(raw, dict):
            continue
        term = str(raw.get("term", "")).strip()
        if not term:
            continue
        entry = {"term": term}
        for f in ("en", "comment"):
            value = str(raw.get(f, "")).strip()
            if value:
                entry[f] = value
        allowed.append(entry)

    return {"forbidden": forbidden, "allowed": allowed}


def _to_guide(data: dict) -> StyleGuide:
    try:
        rules = validate_rules(data.get("rules", []) or [])
    except ValueError:
        rules = []
    try:
        lexicon = validate_lexicon(data.get("lexicon"))
    except ValueError:
        lexicon = {"forbidden": [], "allowed": []}
    return StyleGuide(
        id=str(data.get("id", "")),
        name=str(data.get("name", "")),
        rules=rules,
        builtin=bool(data.get("builtin", False)),
        content_hash=_hash_rules(rules),
        source_filename=str(data.get("source_filename", "")),
        created_at=float(data.get("created_at", 0.0) or 0.0),
        updated_at=float(data.get("updated_at", 0.0) or 0.0),
        created_by=str(data.get("created_by", "")),
        bundle_version=int(data.get("bundle_version", 0) or 0),
        bundled_content_hash=str(data.get("bundled_content_hash", "")),
        lexicon=lexicon,
    )


def _read_file(path: Path) -> StyleGuide | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        logger.warning("Не удалось прочитать гайд %s: %s", path.name, e)
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    return _to_guide(data)


def _write_file(guide: StyleGuide) -> None:
    payload = {
        "id": guide.id,
        "name": guide.name,
        "builtin": guide.builtin,
        "source_filename": guide.source_filename,
        "created_at": guide.created_at,
        "updated_at": guide.updated_at,
        "created_by": guide.created_by,
        "bundle_version": guide.bundle_version,
        "bundled_content_hash": guide.bundled_content_hash,
        "rules": guide.rules,
        "lexicon": guide.lexicon or {"forbidden": [], "allowed": []},
    }
    destination = _path(guide.id)
    temporary = destination.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def _read_bundled_default() -> tuple[list[dict], int]:
    if not DEFAULT_RULES_PATH.exists():
        return [], 0
    try:
        data = yaml.safe_load(DEFAULT_RULES_PATH.read_text(encoding="utf-8")) or {}
        return validate_rules(data.get("rules", []) or []), int(data.get("version", 1) or 1)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
        logger.warning("Не удалось прочитать стартовые правила: %s", e)
        return [], 0


def _backup_modified_default(guide: StyleGuide) -> StyleGuide:
    backup = StyleGuide(
        id=uuid.uuid4().hex[:12],
        name=f"{guide.name} (резервная копия)",
        rules=list(guide.rules),
        builtin=False,
        source_filename=guide.source_filename,
        created_at=time.time(),
        created_by=guide.created_by or "system",
        lexicon=guide.lexicon,
    )
    _write_file(backup)
    return backup


def seed_default() -> None:
    """Сверяет встроенный базовый гайд с сохранённым, не затирая пользовательские правки."""
    with _lock:
        _ensure_dir()
        rules, version = _read_bundled_default()
        if not rules:
            return
        bundled_hash = _hash_rules(rules)
        existing = _read_file(_path(DEFAULT_ID)) if _path(DEFAULT_ID).exists() else None
        if existing is not None:
            if (
                existing.bundle_version == version
                and existing.bundled_content_hash == bundled_hash
                and existing.content_hash == bundled_hash
            ):
                return
            user_modified = (
                not existing.bundled_content_hash
                and existing.content_hash != bundled_hash
            ) or (
                bool(existing.bundled_content_hash)
                and existing.content_hash != existing.bundled_content_hash
            )
            if user_modified:
                backup = _backup_modified_default(existing)
                logger.warning(
                    "Изменённый встроенный гайд сохранён как резервная копия %s",
                    backup.id,
                )
        guide = StyleGuide(
            id=DEFAULT_ID,
            name=DEFAULT_NAME,
            rules=rules,
            builtin=True,
            created_at=time.time(),
            created_by="system",
            bundle_version=version,
            bundled_content_hash=bundled_hash,
        )
        _write_file(guide)
        logger.info("Сидирован встроенный стайл-гайд: %d правил", len(rules))


def list_guides() -> list[StyleGuide]:
    with _lock:
        _ensure_dir()
        guides = [g for g in (_read_file(p) for p in STORE_DIR.glob("*.yaml")) if g]
    guides.sort(key=lambda g: (not g.builtin, g.created_at))
    return guides


def get_guide(guide_id: str) -> StyleGuide | None:
    with _lock:
        try:
            path = _path(guide_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        return _read_file(path)


def save_guide(
    name: str,
    rules: list,
    created_by: str = "",
    source_filename: str = "",
    lexicon=None,
) -> StyleGuide:
    validated = validate_rules(rules)
    with _lock:
        _ensure_dir()
        guide = StyleGuide(
            id=uuid.uuid4().hex[:12],
            name=name.strip() or "Без названия",
            rules=validated,
            builtin=False,
            content_hash=_hash_rules(validated),
            source_filename=source_filename,
            created_at=time.time(),
            created_by=created_by,
            lexicon=validate_lexicon(lexicon),
        )
        _write_file(guide)
    logger.info("Сохранён стайл-гайд %s «%s»: %d правил", guide.id, guide.name, len(validated))
    return guide


def update_guide(
    guide_id: str,
    name: str | None = None,
    rules: list | None = None,
    lexicon=None,
) -> StyleGuide:
    with _lock:
        guide = get_guide(guide_id)
        if guide is None:
            raise KeyError(guide_id)
        if name is not None and name.strip():
            guide.name = name.strip()
        if rules is not None:
            guide.rules = validate_rules(rules)
            guide.content_hash = _hash_rules(guide.rules)
        if lexicon is not None:
            guide.lexicon = validate_lexicon(lexicon)
        guide.updated_at = time.time()
        _write_file(guide)
    logger.info("Обновлён стайл-гайд %s: %d правил, %d запрещённых выражений",
                guide.id, len(guide.rules), len(guide.lexicon_forbidden))
    return guide


def delete_guide(guide_id: str) -> bool:
    with _lock:
        guide = get_guide(guide_id)
        if guide is None:
            return False
        if guide.builtin:
            raise PermissionError("Встроенный гайд нельзя удалить")
        _path(guide_id).unlink(missing_ok=True)
    logger.info("Удалён стайл-гайд %s", guide_id)
    return True

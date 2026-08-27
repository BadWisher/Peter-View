"""Объект стайл-гайда и хелперы форматирования правил для промптов.

Раньше это был глобальный синглтон на один файл. Теперь стайл-гайдов может быть
несколько (см. styleguide_store), поэтому модуль держит только структуру StyleGuide
и чистые функции форматирования, которые принимают набор правил явно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

GENERAL_GROUP = "Общие принципы"
BASE_GROUP = "Базовая грамотность"

# Базовые правила грамотности действуют ВСЕГДА, независимо от выбранного стайл-гайда.
# Они позволяют модели отмечать орфографию/пунктуацию/грамматику/стиль/форматирование,
# даже когда в стайл-гайде нет точечного пункта под конкретный случай. В полной проверке
# LanguageTool не используется, поэтому общую грамотность ловит сама модель.
BASE_RULES: list[dict] = [
    {"rule_id": "Базовая.Орфография", "title": "Орфография", "group": BASE_GROUP,
     "rule": "Опечатки, неверное написание слов, ошибки в окончаниях, слитное/раздельное "
             "написание, пропущенные или лишние буквы."},
    {"rule_id": "Базовая.Пунктуация", "title": "Пунктуация", "group": BASE_GROUP,
     "rule": "Пропущенные или лишние знаки препинания: запятые, точки, тире и дефисы, "
             "кавычки, двоеточия, а также неверные пробелы вокруг знаков."},
    {"rule_id": "Базовая.Грамматика", "title": "Грамматика", "group": BASE_GROUP,
     "rule": "Согласование слов, падежи, род, число, времена, управление, неверный "
             "порядок слов, разорванные или незаконченные конструкции."},
    {"rule_id": "Базовая.Стиль", "title": "Стиль", "group": BASE_GROUP,
     "rule": "Тяжёлые и неоднозначные формулировки, тавтология, многословие, канцелярит, "
             "снижающие читаемость (вне точечных правил стайл-гайда)."},
    {"rule_id": "Базовая.Форматирование", "title": "Форматирование", "group": BASE_GROUP,
     "rule": "Оформление и типографика: единообразие списков и заголовков, регистр, "
             "единицы измерения, лишние/недостающие пробелы и элементы разметки."},
]
BASE_IDS: set[str] = {r["rule_id"] for r in BASE_RULES}

DEFAULT_RULE_METADATA = {
    "categories": [],
    "tasks": [],
    "scope": "all",
    "priority": 50,
    "mandatory": False,
    "machine_verifiable": False,
    "relationships": {},
    "constraints": {},
    "conflict_family": "",
}


def rule_priority(rule: dict) -> int:
    """Числовой приоритет правила, приведённый к диапазону 0-100 (старый и новый формат)."""
    value = rule.get("priority", DEFAULT_RULE_METADATA["priority"])
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_RULE_METADATA["priority"]


def rule_precedence_key(rule: dict) -> tuple:
    """Ключ сортировки: обязательные правила идут раньше желательных и общих."""
    scope = str(rule.get("scope", "all")).strip().lower()
    scope_rank = {"all": 0, "document": 1, "section": 2, "sentence": 3, "token": 4}
    return (
        not bool(rule.get("mandatory", False)),
        -rule_priority(rule),
        -scope_rank.get(scope, 1),
        not bool(rule.get("machine_verifiable", False)),
        str(rule.get("rule_id", rule.get("id", ""))),
    )


def rules_by_precedence(rules: Iterable[dict]) -> list[dict]:
    """Учитывает явные связи supersedes и возвращает правила в стабильном порядке старшинства."""
    materialized = list(rules)
    superseded = {
        str(rule_id)
        for rule in materialized
        for rule_id in (rule.get("relationships", {}) or {}).get("supersedes", []) or []
    }
    return sorted(
        [rule for rule in materialized if str(rule.get("rule_id", "")) not in superseded],
        key=rule_precedence_key,
    )


def authoritative_rules(guide: "StyleGuide", include_base: bool = True) -> list[dict]:
    """Правила гайда старше одноимённых базовых правил с тем же rule_id."""
    guide_ids = guide.ids
    baseline = [rule for rule in BASE_RULES if rule["rule_id"] not in guide_ids] if include_base else []
    return rules_by_precedence([*guide.rules, *baseline])


def _empty_lexicon() -> dict:
    return {"forbidden": [], "allowed": []}


@dataclass
class StyleGuide:
    id: str
    name: str
    rules: list[dict] = field(default_factory=list)
    builtin: bool = False
    content_hash: str = ""
    source_filename: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    created_by: str = ""
    bundle_version: int = 0
    bundled_content_hash: str = ""
    # Лексикон выражений: {"forbidden": [{rule_id, term, replacement, en, comment}],
    #                      "allowed": [{term, en, comment}]}. Проверяется отдельным
    #                      этапом полной проверки (см. worker_8), движок «Правила» его не трогает.
    lexicon: dict = field(default_factory=_empty_lexicon)

    @property
    def ids(self) -> set[str]:
        return {r["rule_id"] for r in self.rules if r.get("rule_id")}

    @property
    def lexicon_forbidden(self) -> list[dict]:
        return (self.lexicon or {}).get("forbidden", []) or []

    @property
    def lexicon_allowed(self) -> list[dict]:
        return (self.lexicon or {}).get("allowed", []) or []

    @property
    def lexicon_ids(self) -> set[str]:
        return {e["rule_id"] for e in self.lexicon_forbidden if e.get("rule_id")}

    @property
    def effective_ids(self) -> set[str]:
        """Валидные rule_id: правила гайда + базовые правила + запрещённые выражения лексикона."""
        return self.ids | BASE_IDS | self.lexicon_ids

    @property
    def retrieval_readiness(self) -> dict:
        """Готовность гайда к поиску: есть ли в правилах текст, примеры и метаданные."""
        total = len(self.rules)
        with_text = sum(bool(r.get("rule") or r.get("generalization")) for r in self.rules)
        with_examples = sum(bool(r.get("bad_examples") or r.get("good_examples")) for r in self.rules)
        with_metadata = sum(
            bool(r.get("categories") or r.get("tasks") or r.get("scope") not in (None, "", "all"))
            for r in self.rules
        )
        inferred = sum(bool(r.get("metadata_inferred")) for r in self.rules)
        ready = total > 0 and with_text == total
        warnings = [] if ready else ["У некоторых правил нет текста для поиска"]
        if inferred:
            warnings.append(
                f"У {inferred} правил поисковые метаданные выведены автоматически"
            )
        return {
            "ready": ready,
            "rule_count": total,
            "rules_with_text": with_text,
            "rules_with_examples": with_examples,
            "rules_with_retrieval_metadata": with_metadata,
            "rules_with_inferred_metadata": inferred,
            "semantic_candidate_count": with_text,
            "warnings": warnings,
        }

    def get_rule(self, rule_id: str) -> dict | None:
        found = next((r for r in self.rules if r.get("rule_id") == rule_id), None)
        if found is not None:
            return found
        found = next((r for r in BASE_RULES if r["rule_id"] == rule_id), None)
        if found is not None:
            return found
        entry = next((e for e in self.lexicon_forbidden if e.get("rule_id") == rule_id), None)
        if entry is not None:
            return {
                "rule_id": rule_id,
                "title": f"Запрещённое выражение: «{entry.get('term', '')}»",
                "rule": entry.get("comment", ""),
            }
        return None


def format_rule(rule: dict) -> str:
    """Компактное текстовое представление правила для промпта."""
    parts = [f"[{rule.get('rule_id', '')}] {rule.get('title', '')}: {rule.get('rule', '')}"]
    if rule.get("generalization"):
        parts.append("  Применимость: " + str(rule["generalization"]))
    if rule.get("good_examples"):
        parts.append("  Хорошо: " + " | ".join(rule["good_examples"]))
    if rule.get("bad_examples"):
        parts.append("  Плохо: " + " | ".join(rule["bad_examples"]))
    if rule.get("constraints"):
        parts.append("  Ограничения: " + str(rule["constraints"]))
    priority = rule_priority(rule)
    scope = str(rule.get("scope", "all"))
    # Дефолтные приоритет и область в промпте не нужны, они ничего не меняют.
    extras = []
    if priority != DEFAULT_RULE_METADATA["priority"]:
        extras.append(f"Приоритет: {priority}")
    if scope != "all":
        extras.append(f"Область: {scope}")
    if extras:
        parts.append("  " + "; ".join(extras))
    return "\n".join(parts)


def format_rules(rules: list[dict]) -> str:
    return "\n".join(format_rule(r) for r in rules)


def general_rules_text(guide: StyleGuide) -> str:
    """Общие правила (тон, аудитория, структура) — всегда в системном промпте."""
    general = [r for r in guide.rules if r.get("group") == GENERAL_GROUP]
    return format_rules(general)


def base_rules_text() -> str:
    """Базовые правила грамотности — всегда в системном промпте (орфография и т.п.)."""
    return format_rules(BASE_RULES)


def all_rules_text(guide: StyleGuide) -> str:
    """Полный список правил — фоллбэк, когда RAG недоступен."""
    return format_rules(guide.rules)


def glossary_text(guide: StyleGuide, limit: int = 60) -> str:
    """Словарь-вотчлист: конкретные «плохие» формулировки -> какое правило задевают.

    Даёт лексическому воркеру явные триггеры (например, «инсталляция», «кликнуть»),
    чтобы он не «забывал» словарные нарушения на длинном тексте. Строится из
    bad_examples любого гайда, поэтому работает и для пользовательских стайл-гайдов.
    """
    lines: list[str] = []
    for rule in guide.rules:
        rule_id = rule.get("rule_id", "")
        for bad in rule.get("bad_examples", []) or []:
            bad = str(bad).strip()
            if bad:
                lines.append(f'- «{bad}» -> может нарушать [{rule_id}]')
            if len(lines) >= limit:
                return "\n".join(lines)
    return "\n".join(lines)


def has_forbidden(guide: StyleGuide) -> bool:
    return bool(guide.lexicon_forbidden)


def forbidden_text(guide: StyleGuide) -> str:
    """Список запрещённых выражений для промпта: rule_id + чем заменить + англ. + комментарий."""
    lines: list[str] = []
    for e in guide.lexicon_forbidden:
        rule_id = e.get("rule_id", "")
        line = f'[{rule_id}] «{e.get("term", "")}»'
        if e.get("replacement"):
            line += f' → заменять на «{e["replacement"]}»'
        if e.get("en"):
            line += f' (англ.: {e["en"]})'
        if e.get("comment"):
            line += f'. {e["comment"]}'
        lines.append(line)
    return "\n".join(lines)


def allowed_text(guide: StyleGuide) -> str:
    """Список разрешённых (каноничных) выражений для промпта."""
    lines: list[str] = []
    for e in guide.lexicon_allowed:
        line = f'- «{e.get("term", "")}»'
        if e.get("en"):
            line += f' (англ.: {e["en"]})'
        if e.get("comment"):
            line += f' — {e["comment"]}'
        lines.append(line)
    return "\n".join(lines)

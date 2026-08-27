"""Одноразовая конвертация style_guide_registry.py -> rules.yaml.

Запускается вручную при первичном сидинге стартового набора правил.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.style_guide_registry import RULES  # noqa: E402

FIELDS = (
    "section", "group", "rule", "generalization", "severity",
    "good_examples", "bad_examples", "categories", "tasks", "scope",
    "priority", "mandatory", "machine_verifiable", "relationships", "constraints",
    "conflict_family",
)

BUNDLE_VERSION = 3


def main() -> None:
    rules = []
    for entry in RULES:
        rule = {"rule_id": entry["id"], "title": entry.get("name", entry["id"])}
        for field in FIELDS:
            if field in entry:
                rule[field] = entry[field]
        rules.append(rule)

    out = Path(__file__).resolve().parent / "rules.yaml"
    header = (
        "# Style Guide для LLM-вычитки.\n"
        "# Редактируйте правила здесь — изменения подхватываются без пересборки образа\n"
        "# (RAG-индекс перестраивается автоматически при смене содержимого файла).\n"
        "# Каждое правило: rule_id (уникальный), title, section, rule, severity, примеры.\n\n"
    )
    with out.open("w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(
            {"version": BUNDLE_VERSION, "rules": rules},
            f,
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )
    print(f"Записано правил: {len(rules)} -> {out}")


if __name__ == "__main__":
    main()

from pathlib import Path

import yaml
import pytest

from app.llm import styleguide_store
from app.style_guide_registry import RULES


ROOT = Path(__file__).parents[1]


def _bundled() -> dict:
    return yaml.safe_load((ROOT / "styleguide" / "rules.yaml").read_text(encoding="utf-8"))


def test_registry_and_bundled_guide_are_synchronized() -> None:
    data = _bundled()
    bundled = {rule["rule_id"]: rule for rule in data["rules"]}
    registry = {rule["id"]: rule for rule in RULES}

    assert data["version"] == 3
    assert bundled.keys() == registry.keys()
    for rule_id, source in registry.items():
        generated = bundled[rule_id]
        assert generated["title"] == source["name"]
        assert generated["rule"] == source["rule"]
        assert generated.get("good_examples", []) == source.get("good_examples", [])
        assert generated.get("bad_examples", []) == source.get("bad_examples", [])


def test_good_and_bad_examples_do_not_contradict_each_other() -> None:
    for rule in _bundled()["rules"]:
        good = {str(value).strip() for value in rule.get("good_examples", [])}
        bad = {str(value).strip() for value in rule.get("bad_examples", [])}
        assert not good.intersection(bad), rule["rule_id"]


def test_every_vale_style_has_an_authoritative_rule() -> None:
    bundled_ids = {rule["rule_id"] for rule in _bundled()["rules"]}
    vale_ids = {
        f"RuStyleGuide.{path.stem}"
        for path in (ROOT / "vale" / "styles" / "RuStyleGuide").glob("*.yml")
    }
    assert vale_ids <= bundled_ids


def test_machine_constraints_are_directional_policy_data() -> None:
    rules = {rule["rule_id"]: rule for rule in _bundled()["rules"]}
    assert rules["RuStyleGuide.Dash_EmDash"]["constraints"] == {
        "forbidden_chars": ["—"],
        "required_chars": ["–"],
    }
    assert rules["RuStyleGuide.LetterYo"]["constraints"] == {
        "forbidden_introduced_chars": ["ё", "Ё"],
    }


def test_uploaded_guide_rejects_unknown_authority_and_supersedes_cycles() -> None:
    with pytest.raises(ValueError, match="неизвестные связанные правила"):
        styleguide_store.validate_rules([{
            "rule_id": "Custom.One",
            "title": "One",
            "rule": "Policy",
            "relationships": {"supersedes": ["Missing.Rule"]},
        }])

    with pytest.raises(ValueError, match="Цикл supersedes"):
        styleguide_store.validate_rules([
            {
                "rule_id": "Custom.One",
                "title": "One",
                "rule": "Policy one",
                "relationships": {"supersedes": ["Custom.Two"]},
            },
            {
                "rule_id": "Custom.Two",
                "title": "Two",
                "rule": "Policy two",
                "relationships": {"supersedes": ["Custom.One"]},
            },
        ])

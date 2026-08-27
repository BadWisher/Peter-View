from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import yaml

from app.llm import rag, styleguide_store
from app.llm.styleguide import StyleGuide, authoritative_rules


def _vectors(texts: list[str]) -> np.ndarray:
    vectors = []
    for text in texts:
        lowered = text.lower()
        vectors.append([1.0, 0.0] if "альфа" in lowered else [0.0, 1.0])
    return np.asarray(vectors, dtype=np.float32)


class StyleGuideAuthorityRag20260724Tests(unittest.TestCase):
    def setUp(self) -> None:
        rag._reset()

    def test_uploaded_unseen_guide_gets_defaults_and_readiness(self) -> None:
        rules = styleguide_store.validate_rules([
            {"title": "Термин орбита", "rule": "Используйте слово орбита."},
        ])
        rule = rules[0]
        self.assertEqual(rule["scope"], "all")
        self.assertEqual(rule["priority"], 50)
        self.assertFalse(rule["mandatory"])
        self.assertEqual(rule["relationships"], {})

        guide = StyleGuide("unseen-custom", "Новый гайд", rules=rules, content_hash="v1")
        self.assertTrue(guide.retrieval_readiness["ready"])
        self.assertEqual(authoritative_rules(guide)[0]["rule_id"], rule["rule_id"])

    def test_hybrid_retrieval_includes_mandatory_and_lexical_match(self) -> None:
        rules = styleguide_store.validate_rules([
            {
                "rule_id": "Custom.Required",
                "title": "Обязательное",
                "rule": "Всегда проверять заголовок.",
                "mandatory": True,
                "priority": 100,
            },
            {
                "rule_id": "Custom.Orbit",
                "title": "Орбита",
                "rule": "Используйте термин орбита.",
                "bad_examples": ["орбитальный баг"],
                "tasks": ["terminology"],
            },
            {
                "rule_id": "Custom.Other",
                "title": "Другое",
                "rule": "Проверяйте таблицы.",
            },
        ])
        guide = StyleGuide("unseen-hybrid", "Гайд", rules=rules, content_hash="v1")
        with patch.object(rag, "_embed", side_effect=_vectors):
            result = rag.retrieve("Исправьте орбитальный баг", guide, 2, task="terminology")

        ids = [rule["rule_id"] for rule in result.rules]
        self.assertIn("Custom.Required", ids)
        self.assertIn("Custom.Orbit", ids)
        self.assertEqual(result.diagnostics["mode"], "hybrid")

    def test_request_embedding_failure_uses_lexical_fallback(self) -> None:
        rules = styleguide_store.validate_rules([
            {
                "rule_id": "Custom.Lexical",
                "title": "Космос",
                "rule": "Не пишите квазары.",
                "bad_examples": ["квазары"],
            },
            {"rule_id": "Custom.Noise", "title": "Таблицы", "rule": "Оформляйте строки."},
        ])
        guide = StyleGuide("request-failure", "Гайд", rules=rules, content_hash="v1")
        with patch.object(rag, "_embed", side_effect=[_vectors(["x"] * 6), RuntimeError("offline")]):
            result = rag.retrieve("квазары видны", guide, 1)

        self.assertEqual(result.rules[0]["rule_id"], "Custom.Lexical")
        self.assertEqual(result.diagnostics["mode"], "lexical")
        self.assertIn("offline", result.diagnostics["request_error"])

    def test_legacy_and_task_aware_entry_points_remain_compatible(self) -> None:
        guide = StyleGuide(
            "api-compatibility",
            "Гайд",
            rules=styleguide_store.validate_rules([
                {
                    "rule_id": "Custom.Alpha",
                    "title": "Альфа",
                    "rule": "Используйте альфа.",
                    "tasks": ["terminology"],
                },
                {"rule_id": "Custom.Beta", "title": "Бета", "rule": "Используйте бета."},
            ]),
            content_hash="v1",
        )
        with patch.object(rag, "_embed", side_effect=_vectors):
            single = rag.top_k("альфа", guide, 1)
            batch = rag.top_k_batch(["альфа", "бета"], guide, 1)
            task = rag.top_k_for_task("альфа", guide, task="terminology", k=1)
            task_batch = rag.top_k_batch_for_task(
                ["альфа"], guide, task="terminology", k=1,
            )

        self.assertEqual(single[0]["rule_id"], "Custom.Alpha")
        self.assertEqual(len(batch), 2)
        self.assertEqual(task[0]["rule_id"], "Custom.Alpha")
        self.assertEqual(task_batch[0][0]["rule_id"], "Custom.Alpha")

    def test_one_failed_guide_does_not_degrade_another(self) -> None:
        failed = StyleGuide(
            "failed-guide", "Сбой",
            rules=styleguide_store.validate_rules([{"title": "Сбой", "rule": "Сломано."}]),
            content_hash="f1",
        )
        healthy = StyleGuide(
            "healthy-guide", "Рабочий",
            rules=styleguide_store.validate_rules([{"title": "Альфа", "rule": "Пишите альфа."}]),
            content_hash="h1",
        )

        with patch.object(rag, "_embed", side_effect=RuntimeError("endpoint down")):
            failed_result = rag.retrieve("сломано", failed, 1)
        with patch.object(rag, "_embed", side_effect=_vectors):
            healthy_result = rag.retrieve("альфа", healthy, 1)

        self.assertFalse(failed_result.diagnostics["semantic_used"])
        self.assertTrue(healthy_result.diagnostics["semantic_used"])
        self.assertEqual(rag.exact_rule(healthy, healthy.rules[0]["rule_id"]), healthy.rules[0])

    def test_versioned_reconciliation_backs_up_user_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "store"
            store.mkdir()
            bundle = root / "rules.yaml"
            bundled_rules = styleguide_store.validate_rules([
                {"rule_id": "Bundled.New", "title": "Новое", "rule": "Новая редакция."},
            ])
            bundle.write_text(
                yaml.safe_dump({"version": 2, "rules": bundled_rules}, allow_unicode=True),
                encoding="utf-8",
            )
            old_rules = styleguide_store.validate_rules([
                {"rule_id": "Bundled.Old", "title": "Старое", "rule": "Старая редакция."},
            ])
            modified_rules = styleguide_store.validate_rules([
                {"rule_id": "User.Edit", "title": "Правка", "rule": "Пользовательская правка."},
            ])
            existing = StyleGuide(
                "default", "Базовый", rules=modified_rules, builtin=True,
                bundle_version=1,
                bundled_content_hash=styleguide_store._hash_rules(old_rules),
            )
            with (
                patch.object(styleguide_store, "STORE_DIR", store),
                patch.object(styleguide_store, "DEFAULT_RULES_PATH", bundle),
            ):
                styleguide_store._write_file(existing)
                styleguide_store.seed_default()
                reconciled = styleguide_store.get_guide("default")
                backups = [guide for guide in styleguide_store.list_guides() if not guide.builtin]

            self.assertEqual(reconciled.bundle_version, 2)
            self.assertEqual(reconciled.rules[0]["rule_id"], "Bundled.New")
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].rules[0]["rule_id"], "User.Edit")


if __name__ == "__main__":
    unittest.main()

"""Регрессии на фиксы из аудита: аналитика, regex, ключ мониторинга."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import checker
from app.llm import watch_store as store
from app.routers import history
from app.net_guard import is_blocked_navigation


class UserRuleRegexTests(unittest.TestCase):
    def test_bad_pattern_is_skipped_not_raised(self):
        # Паттерн компилируется движком regex, а regex.error не наследник
        # re.error. Если в except стоит re.error, битый паттерн уронит всю
        # проверку исключением вместо того, чтобы просто пропустить правило.
        rules = [{"pattern": "(?<", "message": "битый", "severity": "error"}]
        issues = checker._apply_user_rules("обычный текст без совпадений", rules)
        self.assertEqual(issues, [])


class AnalyticsImportTests(unittest.TestCase):
    def test_rule_titles_resolves_styleguide(self):
        # В history.py был ленивый импорт from .llm import styleguide, который
        # резолвился в несуществующий app.routers.llm и давал 500 на аналитике.
        with patch.object(history, "styleguide_store") as guides:
            guides.list_guides.return_value = []
            titles = history._rule_titles()
        # Без падения импорта и заголовки базовых правил на месте.
        self.assertTrue(titles)
        self.assertTrue(all(isinstance(t, str) for t in titles.values()))


class WatchSecretTests(unittest.TestCase):
    def test_secret_not_hardcoded_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(store, "DB_FILE", Path(tmp) / "watch.db"):
                store._secret_key = None
                with patch.dict("os.environ", {"PROOFREADER_SECRET": ""}, clear=False):
                    secret = store._secret()
                # Дефолтный ключ из открытого репозитория больше не используется.
                self.assertNotEqual(secret, b"proofreader-local-watch")
                self.assertTrue(len(secret) >= 32)
                # Ключ переживает перезапуск: сохранён рядом с базой и тот же.
                again = store._secret()
                self.assertEqual(secret, again)

    def test_encrypt_roundtrip_and_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(store, "DB_FILE", Path(tmp) / "watch.db"):
                store._secret_key = None
                blob = store.encrypt_secret("Портальный-пароль")
                self.assertEqual(store.decrypt_secret(blob), "Портальный-пароль")
                self.assertNotIn("Портальный", blob)
                key_file = store._secret_file()
                self.assertTrue(key_file.exists())
                self.assertEqual(key_file.stat().st_mode & 0o077, 0o000)


class NavigationGuardTests(unittest.TestCase):
    def test_loopback_blocked_unknown_host_lets_through(self):
        async def run():
            self.assertTrue(await is_blocked_navigation("http://127.0.0.1:8000/x"))
            self.assertTrue(await is_blocked_navigation("http://169.254.169.254/"))
            # Хост, который не разрешился, гвард не блокирует: иначе легитимный
            # съём деградировал бы в ошибку вместо отката на голую страницу.
            self.assertFalse(await is_blocked_navigation("http://no-such-host.invalid/"))
            self.assertFalse(await is_blocked_navigation("ftp://example.com"))
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

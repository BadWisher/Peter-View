import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import audit, auth, features
from app.llm import settings as llm_settings


class RoleStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        data = Path(self._tmp.name)
        self._users = patch.object(auth, "USERS_FILE", data / "users.json")
        self._users.start()
        self.addCleanup(self._users.stop)
        self._dir = patch.object(auth, "DATA_DIR", data)
        self._dir.start()
        self.addCleanup(self._dir.stop)
        auth.SESSIONS.clear()

    def test_seed_admin(self):
        auth.seed_default_admin()
        users = auth.read_users()
        self.assertEqual(users["admin"]["role"], "admin")
        self.assertTrue(auth.check_password("admin", users["admin"]["password"]))

    def test_legacy_hash_becomes_admin_for_admin_login(self):
        hashed = auth.hash_password("secret12")
        (auth.USERS_FILE).write_text(json.dumps({"admin": hashed, "ivan": hashed}), encoding="utf-8")
        users = auth.read_users()
        self.assertEqual(users["admin"]["role"], "admin")
        self.assertEqual(users["ivan"]["role"], "editor")

    def test_cannot_drop_last_admin(self):
        auth.seed_default_admin()
        self.assertEqual(auth.admin_count(), 1)
        self.assertEqual(auth.MIN_PASSWORD, 8)


class FeatureFlagTests(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FEATURE_DOCUMENTS", None)
            self.assertFalse(features.enabled("documents"))
            self.assertTrue(features.enabled("check"))

    def test_enable_documents(self):
        with patch.dict(os.environ, {"FEATURE_DOCUMENTS": "true"}):
            self.assertTrue(features.enabled("documents"))
            dep = features.require_feature("api")
            with self.assertRaises(HTTPException):
                dep()


class SettingsDefaultsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "llm_settings.json"
        self._file = patch.object(llm_settings, "SETTINGS_FILE", path)
        self._file.start()
        self.addCleanup(self._file.stop)
        llm_settings._cache = None

    def tearDown(self):
        llm_settings._cache = None

    def test_empty_llm_default(self):
        with patch.dict(os.environ, {"LLM_BASE_URL": "", "EMBEDDING_BASE_URL": ""}, clear=False):
            llm_settings._cache = None
            self.assertEqual(llm_settings.get_value("llm_base_url"), "")
            self.assertNotIn("easter_eggs", llm_settings.get_masked())


class AuditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        data = Path(self._tmp.name)
        patcher = patch.object(audit, "DATA_DIR", data)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher2 = patch.object(audit, "AUDIT_FILE", data / "audit.jsonl")
        patcher2.start()
        self.addCleanup(patcher2.stop)

    def test_append_and_read(self):
        audit.append("login", "admin", source="local")
        rows = audit.recent()
        self.assertEqual(rows[0]["action"], "login")
        self.assertEqual(rows[0]["user"], "admin")


if __name__ == "__main__":
    unittest.main()

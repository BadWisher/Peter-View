import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.llm import watch_run
from app.llm import watch_store as store


class WatchStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "watch.db"
        self._db_patch = patch.object(store, "DB_FILE", self.db)
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)
        store._init_db()

    def test_encrypt_roundtrip(self):
        blob = store.encrypt_secret("PortalPass")
        self.assertNotIn("PortalPass", blob)
        self.assertEqual(store.decrypt_secret(blob), "PortalPass")

    def test_group_and_page(self):
        group = store.create_group(
            "Клиентский портал",
            auth_kind="form",
            login_url="https://portal.example.test/login",
            username="docs",
            password="secret",
            created_by="editor",
        )
        self.assertTrue(group["has_password"])
        self.assertNotIn("password", group)
        page = store.add_page(group["id"], "https://portal.example.test/policies", "Политики")
        store.record_snapshot(page["id"], text="старый", content_hash="a", changed=False)
        store.record_snapshot(page["id"], text="новый", content_hash="b", changed=True)
        listed = store.list_groups()
        self.assertEqual(listed[0]["changed_count"], 1)
        snaps = store.latest_snapshots(page["id"], limit=2)
        self.assertEqual(snaps[0]["text"], "новый")
        self.assertEqual(len(store.list_snapshots(page["id"])), 2)

    def test_form_login_url_required(self):
        with self.assertRaises(ValueError):
            store.create_group("Портал", auth_kind="form", login_url="not-a-url")


class WatchDiffTests(unittest.TestCase):
    def test_fingerprint_stable(self):
        text = watch_run.snapshot_text("<html><body><h1>Портал</h1><script>x=1</script><p>Срок 90 дней</p></body></html>")
        self.assertIn("Портал", text)
        self.assertNotIn("x=1", text)
        self.assertEqual(watch_run.fingerprint(text), hashlib.sha256(text.encode()).hexdigest())

    def test_hunks_mark_replacements(self):
        hunks = watch_run.text_hunks("Срок 90 дней\nКонец", "Срок 60 дней\nКонец")
        ops = [item["op"] for item in hunks]
        self.assertIn("del", ops)
        self.assertIn("add", ops)


if __name__ == "__main__":
    unittest.main()

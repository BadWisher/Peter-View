import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

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


def _resp(text: str, status: int = 200) -> httpx.Response:
    req = httpx.Request("GET", "https://portal.example.test/policies")
    return httpx.Response(status_code=status, text=text, request=req)


class WatchFetchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "watch.db"
        self._db_patch = patch.object(store, "DB_FILE", self.db)
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)
        store._init_db()

    def _group_page(self, **kw):
        group = store.create_group("Портал", auth_kind="none", created_by="editor")
        page = store.add_page(group["id"], "https://portal.example.test/policies", "Политики")
        return group, page

    def test_empty_snapshot_is_error_not_same(self):
        _, page = self._group_page()
        body = "<html><body><div id='app'></div><script>render()</script></body></html>"
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(body))):
            result = asyncio.run(watch_run.check_page(page["id"]))
        self.assertEqual(result["last_status"], "error")
        self.assertIn("почти пусто", result["last_error"])

    def test_changed_page_detected(self):
        _, page = self._group_page()
        first = "<html><body><article><h1>Регламент доступа</h1><p>Срок действия пароля: 90 дней. Регламент общий для всех.</p></article></body></html>"
        second = "<html><body><article><h1>Регламент доступа</h1><p>Срок действия пароля: 60 дней. Регламент общий для всех.</p></article></body></html>"
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(first))):
            asyncio.run(watch_run.check_page(page["id"]))
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(second))):
            result = asyncio.run(watch_run.check_page(page["id"]))
        self.assertEqual(result["last_status"], "changed")
        diff = watch_run.page_diff(page["id"])
        ops = [h["op"] for h in diff["hunks"]]
        self.assertIn("del", ops)
        self.assertIn("add", ops)

    def test_date_only_change_is_ignored(self):
        _, page = self._group_page()
        first = "<html><body><article><h1>Регламент доступа</h1><p>Срок действия пароля: 90 дней. Обновлено 01.09.2026.</p></article></body></html>"
        second = "<html><body><article><h1>Регламент доступа</h1><p>Срок действия пароля: 90 дней. Обновлено 05.09.2026.</p></article></body></html>"
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(first))):
            asyncio.run(watch_run.check_page(page["id"]))
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(second))):
            result = asyncio.run(watch_run.check_page(page["id"]))
        self.assertEqual(result["last_status"], "same")

    def test_word_marks_point_at_changed_word(self):
        hunks = watch_run.text_hunks("Срок действия пароля: 90 дней", "Срок действия пароля: 60 дней")
        add = next(h for h in hunks if h["op"] == "add")
        changed = [w for w, same in zip(add["words"], add["same"]) if not same]
        self.assertEqual(changed, ["60"])


if __name__ == "__main__":
    unittest.main()

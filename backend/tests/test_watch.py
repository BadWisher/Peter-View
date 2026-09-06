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


class WatchDomTests(unittest.TestCase):
    def test_new_button_is_added_event_with_position(self):
        before = "<html><body><main><h1>Регламент</h1></main></body></html>"
        after = "<html><body><main><h1>Регламент</h1><a href='/v2'>Новая версия</a></main></body></html>"
        events = watch_run.watch_dom.diff_nodes(
            watch_run.watch_dom.snapshot_nodes(before),
            watch_run.watch_dom.snapshot_nodes(after),
        )
        added = [e for e in events if e["kind"] == "added"]
        self.assertTrue(added)
        self.assertIn("a", [e["tag"] for e in added])
        self.assertTrue(all(e["path"] for e in added))

    def test_moved_block_is_moved_not_add_remove(self):
        before = ("<html><body><main><p>Первый</p><p>Второй</p></main></body></html>")
        after = ("<html><body><main><p>Второй</p><p>Первый</p></main></body></html>")
        events = watch_run.watch_dom.diff_nodes(
            watch_run.watch_dom.snapshot_nodes(before),
            watch_run.watch_dom.snapshot_nodes(after),
        )
        kinds = {e["kind"] for e in events}
        self.assertIn("moved", kinds)
        self.assertNotIn("added", kinds)
        self.assertNotIn("removed", kinds)

    def test_href_change_is_attr_event(self):
        before = "<html><body><main><a href='/v1'>Скачать</a></main></body></html>"
        after = "<html><body><main><a href='/v2'>Скачать</a></main></body></html>"
        events = watch_run.watch_dom.diff_nodes(
            watch_run.watch_dom.snapshot_nodes(before),
            watch_run.watch_dom.snapshot_nodes(after),
        )
        self.assertEqual([e["kind"] for e in events], ["attr"])
        self.assertIn("ссылка", events[0]["detail"])

    def test_tag_change_is_tag_event(self):
        before = "<html><body><main><p>Заголовок</p></main></body></html>"
        after = "<html><body><main><h2>Заголовок</h2></main></body></html>"
        events = watch_run.watch_dom.diff_nodes(
            watch_run.watch_dom.snapshot_nodes(before),
            watch_run.watch_dom.snapshot_nodes(after),
        )
        self.assertEqual([e["kind"] for e in events], ["tag"])

    def test_date_only_change_is_quiet(self):
        before = "<html><body><main><p>Обновлено 01.09.2026</p></main></body></html>"
        after = "<html><body><main><p>Обновлено 05.09.2026</p></main></body></html>"
        events = watch_run.watch_dom.diff_nodes(
            watch_run.watch_dom.snapshot_nodes(before),
            watch_run.watch_dom.snapshot_nodes(after),
        )
        self.assertEqual(events, [])

    def test_struct_change_flips_status_without_text_change(self):
        group = store.create_group("Портал", auth_kind="none", created_by="editor")
        page = store.add_page(group["id"], "https://portal.example.test/ui", "Интерфейс")
        first = "<html><body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p></main></body></html>"
        second = ("<html><body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p>"
                  "<a href='/v2'>Новая версия регламента</a></main></body></html>")
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(first))):
            asyncio.run(watch_run.check_page(page["id"]))
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(second))):
            result = asyncio.run(watch_run.check_page(page["id"]))
        self.assertEqual(result["last_status"], "changed")
        diff = watch_run.page_diff(page["id"])
        self.assertTrue([e for e in diff["ui"] if e["kind"] == "added"])


class WatchCopyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "watch.db"
        self._db_patch = patch.object(store, "DB_FILE", self.db)
        self._db_patch.start()
        self.addCleanup(self._db_patch.stop)
        store._init_db()

    def _two_snaps(self):
        group = store.create_group("Портал", auth_kind="none", created_by="editor")
        page = store.add_page(group["id"], "https://portal.example.test/copy", "Копия")
        first = ("<html><body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p>"
                 "<a href='/v1'>Скачать PDF</a><script>steal()</script></main></body></html>")
        second = ("<html><body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p>"
                  "<a href='/v2'>Скачать PDF</a><a href='/new'>Новая версия регламента</a></main></body></html>")
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(first))):
            asyncio.run(watch_run.check_page(page["id"]))
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(second))):
            asyncio.run(watch_run.check_page(page["id"]))
        return page

    def test_copy_has_no_scripts_but_marks_changes(self):
        page = self._two_snaps()
        copy = watch_run.page_copy(page["id"])
        self.assertNotIn("<script", copy)
        self.assertNotIn("steal()", copy)
        self.assertIn("pvwatch-is-added", copy)
        self.assertIn("pvwatch-is-attr", copy)
        self.assertIn("Новая версия регламента", copy)

    def test_copy_is_document_with_native_styles_and_base(self):
        group = store.create_group("Портал", auth_kind="none", created_by="editor")
        page = store.add_page(group["id"], "https://portal.example.test/styled", "Стили")
        first = ("<html><head><style>body{font-family:serif}</style></head>"
                 "<body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p></main></body></html>")
        second = ("<html><head><style>body{font-family:serif}</style></head>"
                  "<body><main><h1>Регламент</h1><p>Текст тот же самый длинный!</p></main></body></html>")
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(first))):
            asyncio.run(watch_run.check_page(page["id"]))
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(second))):
            asyncio.run(watch_run.check_page(page["id"]))
        copy = watch_run.page_copy(page["id"])
        self.assertTrue(copy.startswith("<!DOCTYPE html>"))
        self.assertIn("font-family:serif", copy)
        self.assertIn('<base href="https://portal.example.test/styled" target="_blank">', copy)
        self.assertIn("pvwatch-is-", copy)

    def test_copy_shows_ghost_where_block_was_removed(self):
        group = store.create_group("Портал", auth_kind="none", created_by="editor")
        page = store.add_page(group["id"], "https://portal.example.test/gone", "Пропажа")
        first = ("<html><body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p>"
                 "<a href='/v1'>Скачать PDF</a><a href='/x'>Лишняя ссылка для удаления</a></main></body></html>")
        second = ("<html><body><main><h1>Регламент</h1><p>Текст тот же самый длинный.</p>"
                  "<a href='/v1'>Скачать PDF</a></main></body></html>")
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(first))):
            asyncio.run(watch_run.check_page(page["id"]))
        with patch.object(watch_run, "safe_request", new=AsyncMock(return_value=_resp(second))):
            asyncio.run(watch_run.check_page(page["id"]))
        copy = watch_run.page_copy(page["id"])
        self.assertIn("pvwatch-ghost", copy)
        self.assertIn("Лишняя ссылка для удаления", copy)

    def test_diff_stays_light_copy_flag_only(self):
        page = self._two_snaps()
        diff = watch_run.page_diff(page["id"])
        self.assertTrue(diff["has_copy"])
        self.assertNotIn("copy", diff)
        copy = watch_run.page_copy(page["id"])
        self.assertIn("Новая версия регламента", copy)


if __name__ == "__main__":
    unittest.main()

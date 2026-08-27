import re
import unittest
from unittest.mock import AsyncMock, patch

from app.llm.documents import Block, Document
from app.llm.extractor import ExtractionResult, _split_document, extract_rules


def _block(index: int, text: str, block_type: str = "paragraph") -> Block:
    return Block(index=index, raw=text, plain=text, metadata={"type": block_type})


class StyleguideExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_document_extracts_rules_from_every_block(self):
        document = Document([
            _block(index, f"Уникальное правило {index}: " + "требование " * 12)
            for index in range(250)
        ])

        async def fake_extract(chunk: str) -> list[dict]:
            return [
                {
                    "title": f"Правило {index}",
                    "rule": f"Требование {index}",
                }
                for index in re.findall(r"\[Блок (\d+),", chunk)
            ]

        with patch(
            "app.llm.extractor._extract_chunk",
            new=AsyncMock(side_effect=fake_extract),
        ) as mocked:
            result = await extract_rules(document)

        self.assertGreater(mocked.await_count, 1)
        self.assertEqual(len(result.rules), 250)
        self.assertEqual(result.chunks_failed, 0)
        self.assertEqual(result.chunks_succeeded, result.chunks_total)

    async def test_failed_chunk_is_reported_as_partial(self):
        document = Document([
            _block(index, f"Правило {index}: " + "текст " * 150)
            for index in range(12)
        ])
        calls = 0

        async def sometimes_fails(_chunk: str) -> list[dict]:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("provider failure")
            return [{"title": f"Пакет {calls}", "rule": "Проверять требование"}]

        with patch(
            "app.llm.extractor._extract_chunk",
            new=AsyncMock(side_effect=sometimes_fails),
        ):
            result = await extract_rules(document)

        self.assertIsInstance(result, ExtractionResult)
        self.assertTrue(result.partial)
        self.assertEqual(result.chunks_failed, 1)
        self.assertEqual(
            result.chunks_succeeded + result.chunks_failed,
            result.chunks_total,
        )

    async def test_same_title_with_different_rule_text_is_not_discarded(self):
        document = Document([_block(0, "Исходные требования")])
        extracted = [
            {"title": "Названия элементов", "rule": "Кнопки заключают в кавычки."},
            {"title": "Названия элементов", "rule": "Вкладки пишут с прописной буквы."},
        ]

        with patch(
            "app.llm.extractor._extract_chunk",
            new=AsyncMock(return_value=extracted),
        ):
            result = await extract_rules(document)

        self.assertEqual(len(result.rules), 2)

    def test_oversized_block_is_split_without_losing_tail(self):
        marker = "КОНЕЦ_ПРАВИЛА"
        document = Document([_block(0, ("слово " * 1500) + marker)])

        chunks = _split_document(document)

        self.assertGreater(len(chunks), 1)
        self.assertIn(marker, chunks[-1])
        self.assertTrue(all(len(chunk) <= 3500 for chunk in chunks))

    async def test_lexicon_terms_are_merged_across_chunks(self):
        document = Document([
            _block(0, "Словарь запрещённых выражений. " + "требование " * 200),
            _block(1, "Рекомендуемые формулировки. " + "требование " * 200),
        ])
        payloads = [
            {
                "rules": [{"title": "Клик", "rule": "Не писать «кликнуть»."}],
                "lexicon": {
                    "forbidden": [{"term": "кликнуть", "replacement": "нажать"}],
                    "allowed": [],
                },
            },
            {
                "rules": [{"title": "Кавычки", "rule": "Кнопки в кавычках."}],
                "lexicon": {
                    "forbidden": [{"term": "кликнуть", "comment": "интерфейс"}],
                    "allowed": [{"term": "нажать"}],
                },
            },
        ]

        with patch(
            "app.llm.extractor._extract_chunk",
            new=AsyncMock(side_effect=payloads),
        ):
            result = await extract_rules(document)

        self.assertEqual(len(result.rules), 2)
        self.assertEqual(len(result.lexicon["forbidden"]), 1)
        forbidden = result.lexicon["forbidden"][0]
        self.assertEqual(forbidden["term"], "кликнуть")
        self.assertEqual(forbidden.get("replacement"), "нажать")
        self.assertEqual(forbidden.get("comment"), "интерфейс")
        self.assertEqual(result.lexicon["allowed"][0]["term"], "нажать")


if __name__ == "__main__":
    unittest.main()

"""LLM-извлечение структурированных правил из текста стайл-гайда (docx).

Текст гайда — это проза, поэтому правила достаём моделью: режем на куски, по каждому
куску просим список правил, затем объединяем и дедуплицируем. Результат отдаётся на
предпросмотр пользователю, сохранение — отдельным шагом.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .client import complete_json
from .documents import Block, Document
from .workers import _env  # переиспользуем настроенное окружение Jinja

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]

CHUNK_CHARS = 3500
CHUNK_OVERLAP_PARAS = 1
EXTRACT_CONCURRENCY = max(1, int(os.getenv("STYLEGUIDE_EXTRACT_CONCURRENCY", "3")))
EXTRACTOR_SYSTEM = (
    "Ты — методист, который формализует редакционные стайл-гайды в проверяемые правила. "
    "Работаешь точно и не выдумываешь требований сверх текста."
)


@dataclass
class ExtractionResult:
    rules: list[dict]
    chunks_total: int
    chunks_succeeded: int
    chunks_failed: int
    chunks_empty: int
    lexicon: dict = field(default_factory=lambda: {"forbidden": [], "allowed": []})

    @property
    def partial(self) -> bool:
        return self.chunks_failed > 0


def _split_oversized(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Режет слишком длинный блок на части, не теряя ни одного символа."""
    remaining = text.strip()
    parts: list[str] = []
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _block_text(block: Block, heading: str) -> str:
    block_type = str(block.metadata.get("type") or "paragraph")
    level = block.metadata.get("level")
    label = block_type + (f"/{level}" if level else "")
    context = f"Раздел: {heading}\n" if heading and block_type != "heading" else ""
    return f"{context}[Блок {block.index}, {label}]\n{block.plain.strip()}"


def _document_units(document: Document) -> list[str]:
    units: list[str] = []
    heading = ""
    for block in document.blocks:
        if not block.plain.strip():
            continue
        if block.metadata.get("type") == "heading":
            heading = block.plain.strip()
        units.extend(_split_oversized(_block_text(block, heading)))
    return units


def _split_document(document: Document) -> list[str]:
    """Собирает блоки документа в чанки ограниченного размера."""
    units = _document_units(document)
    if not units:
        return []

    chunks: list[str] = []
    buffer: list[str] = []
    size = 0
    for unit in units:
        added = len(unit) + (2 if buffer else 0)
        if buffer and size + added > CHUNK_CHARS:
            chunks.append("\n\n".join(buffer))
            buffer = buffer[-CHUNK_OVERLAP_PARAS:] if CHUNK_OVERLAP_PARAS else []
            size = sum(len(item) for item in buffer) + max(0, len(buffer) - 1) * 2
            if buffer and size + len(unit) + 2 > CHUNK_CHARS:
                buffer = []
                size = 0
        buffer.append(unit)
        size += len(unit) + (2 if len(buffer) > 1 else 0)
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


def _empty_lexicon() -> dict:
    return {"forbidden": [], "allowed": []}


def _has_lexicon(lexicon: dict) -> bool:
    return bool((lexicon or {}).get("forbidden") or (lexicon or {}).get("allowed"))


def _chunk_payload(raw) -> tuple[list[dict], dict]:
    """Принимает и новый объект {rules, lexicon}, и старый список правил из тестов."""
    if isinstance(raw, list):
        return raw, _empty_lexicon()
    if not isinstance(raw, dict):
        return [], _empty_lexicon()
    rules = raw.get("rules")
    if not isinstance(rules, list):
        rules = []
    lexicon = raw.get("lexicon") if isinstance(raw.get("lexicon"), dict) else _empty_lexicon()
    return rules, lexicon


def _merge_lexicon_entry(prev: dict, raw: dict, term: str) -> dict:
    entry = {**prev, "term": term}
    for field_name in ("replacement", "en", "comment"):
        value = str(raw.get(field_name) or "").strip() or str(prev.get(field_name) or "").strip()
        if value:
            entry[field_name] = value
        else:
            entry.pop(field_name, None)
    return entry


def _merge_lexicon(batches: list[dict]) -> dict:
    forbidden: dict[str, dict] = {}
    allowed: dict[str, dict] = {}
    for lexicon in batches:
        if not isinstance(lexicon, dict):
            continue
        for raw in lexicon.get("forbidden") or []:
            if not isinstance(raw, dict):
                continue
            term = str(raw.get("term", "")).strip()
            if not term:
                continue
            key = _normalize_term(term)
            forbidden[key] = _merge_lexicon_entry(forbidden.get(key, {}), raw, term)
        for raw in lexicon.get("allowed") or []:
            if not isinstance(raw, dict):
                continue
            term = str(raw.get("term", "")).strip()
            if not term:
                continue
            key = _normalize_term(term)
            allowed[key] = _merge_lexicon_entry(allowed.get(key, {}), raw, term)
    return {
        "forbidden": list(forbidden.values()),
        "allowed": list(allowed.values()),
    }


async def _extract_chunk(chunk: str) -> dict:
    user = _env.get_template("extractor.jinja2").render(chunk=chunk)
    response = await complete_json(EXTRACTOR_SYSTEM, user)
    return response if isinstance(response, dict) else {"rules": []}


async def extract_rules(
    document: Document,
    progress: ProgressCb | None = None,
) -> ExtractionResult:
    """Извлекает правила из каждого чанка документа и считает полноту покрытия."""
    def report(stage: str) -> None:
        if progress:
            progress(stage)

    chunks = _split_document(document)
    if not chunks:
        return ExtractionResult([], 0, 0, 0, 0)

    report(f"Извлечение правил: 0 из {len(chunks)}")
    done = 0
    failed = 0
    empty = 0
    semaphore = asyncio.Semaphore(EXTRACT_CONCURRENCY)

    async def run(chunk: str) -> tuple[list[dict], dict]:
        nonlocal done, failed, empty
        try:
            async with semaphore:
                raw = await _extract_chunk(chunk)
            rules, lexicon = _chunk_payload(raw)
            if not rules and not _has_lexicon(lexicon):
                empty += 1
            return rules, lexicon
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning("Не удалось извлечь правила из куска: %s", e)
            return [], _empty_lexicon()
        finally:
            done += 1
            report(f"Извлечение правил: {done} из {len(chunks)}")

    batches = await asyncio.gather(*(run(c) for c in chunks))

    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    lexicon_batches: list[dict] = []
    for batch_rules, batch_lexicon in batches:
        lexicon_batches.append(batch_lexicon)
        for raw in batch_rules:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title", "")).strip()
            rule_text = str(raw.get("rule", "")).strip()
            if not title and not rule_text:
                continue
            key = (
                _normalize_title(title or rule_text),
                re.sub(r"\s+", " ", rule_text.strip().lower()),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append({
                "title": title or rule_text[:60],
                "rule": rule_text,
                "group": str(raw.get("group", "")).strip(),
                "severity": str(raw.get("severity", "")).strip().lower() or "suggestion",
                "good_examples": [str(x).strip() for x in (raw.get("good_examples") or []) if str(x).strip()],
                "bad_examples": [str(x).strip() for x in (raw.get("bad_examples") or []) if str(x).strip()],
            })

    lexicon = _merge_lexicon(lexicon_batches)
    succeeded = len(chunks) - failed
    logger.info(
        "Извлечено правил из гайда: %d, лексикон: %d запрещённых / %d разрешённых "
        "(кусков: %d, успешно: %d, ошибки: %d, пусто: %d)",
        len(merged),
        len(lexicon.get("forbidden") or []),
        len(lexicon.get("allowed") or []),
        len(chunks), succeeded, failed, empty,
    )
    return ExtractionResult(merged, len(chunks), succeeded, failed, empty, lexicon)

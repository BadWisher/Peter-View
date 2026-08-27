"""Качество-ориентированный пайплайн вычитки v2.

Версия v2 используется по умолчанию (PIPELINE_VERSION=v2). v1 остаётся для отката
и быстрого отката, пока метрики и ручная проверка не подтвердят улучшение.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import os
import re
import time
from typing import Awaitable, Callable, TypeVar

from . import rag, stats as usage_stats
from .chunking import chunk_blocks
from .documents import Block, Document
from .evidence import collect_engine_evidence, collect_lexicon_evidence
from .pipeline import (
    MAX_CHUNKS_TARGET,
    MIN_BLOCKS_FOR_CONSISTENCY,
    _Stats,
    _build_report,
    _dedupe,
    _empty_report,
    _plan,
)
from .styleguide import StyleGuide, rule_precedence_key
from .workers import (
    worker_consistency,
    worker_guide_local,
    worker_language,
    worker_structure,
    worker_terminology,
    worker_verifier,
)

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]
StreamCb = Callable[[dict], None]
VERIFY_BATCH = 12
MAX_CONSISTENCY_BLOCKS = 80
WINDOW_BLOCKS = 6
PASS_TIMEOUT = float(os.getenv("PIPELINE_V2_PASS_TIMEOUT", "360"))
PASS_RETRIES = int(os.getenv("PIPELINE_V2_PASS_RETRIES", "2"))
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё][\w-]{3,}")

_T = TypeVar("_T")


def _pass_error_message(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return f"таймаут прохода ({PASS_TIMEOUT:.0f} с)"
    text = str(exc).strip()
    return text or repr(exc)


def _pass_retriable(exc: BaseException) -> bool:
    from .client import LLMRequestError
    if isinstance(exc, asyncio.TimeoutError):
        return True
    if isinstance(exc, LLMRequestError):
        return True
    if isinstance(exc, RuntimeError) and "LLM-запрос не удался" in str(exc):
        return True
    return False


async def _retry_pass(
    make_coro: Callable[[], Awaitable[_T]],
    *,
    worker_name: str,
    scope: str,
) -> _T:
    last_exc: BaseException | None = None
    for attempt in range(PASS_RETRIES + 1):
        try:
            return await asyncio.wait_for(make_coro(), timeout=PASS_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < PASS_RETRIES and _pass_retriable(exc):
                wait = min(10, 2 ** attempt)
                logger.warning(
                    "v2-воркер %s (%s), повтор %d/%d через %ds: %s",
                    worker_name,
                    scope,
                    attempt + 1,
                    PASS_RETRIES,
                    wait,
                    _pass_error_message(exc),
                )
                await asyncio.sleep(wait)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("цикл повторов прохода завершился без результата")

WORKER_NAMES = {
    0: "Детерминированные сигналы",
    1: "Язык",
    2: "Структура",
    4: "Style Guide",
    5: "Терминология",
    6: "Верификатор",
    7: "Согласованность",
}


def _enabled(stage: str) -> bool:
    configured = {
        value.strip().lower()
        for value in os.getenv(
            "PIPELINE_V2_STAGES",
            "evidence,language,guide,structure,terminology,consistency,lexicon,verifier",
        ).split(",")
        if value.strip()
    }
    return stage in configured


def _chunk_context(document: Document, chunk) -> str:
    """Локальное окно соседних блоков вокруг фрагмента.

    Полный сжатый документ здесь не нужен: кросс-ссылки проверяют терминология
    и согласованность, которым контекст передаётся отдельно. А повтор одних и
    тех же ~12k символов в каждом из ~20 чанковых промптов стоит токенов.
    """
    positions = {block.index: pos for pos, block in enumerate(document.blocks)}
    start_positions = [positions[b.index] for b in chunk.blocks if b.index in positions]
    if not start_positions:
        return ""
    start, end = min(start_positions), max(start_positions)
    window = (
        document.blocks[max(0, start - WINDOW_BLOCKS):start]
        + document.blocks[end + 1:end + 1 + WINDOW_BLOCKS]
    )
    chunk_ids = {block.index for block in chunk.blocks}
    return "\n".join(
        f"[{block.index}] {block.plain}"
        for block in window
        if block.index not in chunk_ids and block.plain
    )


def _has_structure(chunk) -> bool:
    for block in chunk.blocks:
        block_type = str((block.metadata or {}).get("type", "paragraph"))
        if block_type not in {"paragraph", "p"} or block.raw != block.plain:
            return True
        if any(key in (block.metadata or {}) for key in ("links", "list_kind", "list_depth")):
            return True
    return False


def _has_prose(chunk) -> bool:
    """Есть ли в чанке связный текст: предложения, а не подписи и оглавления."""
    for block in chunk.blocks:
        text = str(block.plain).strip()
        if len(text) >= 40 and re.search(r"[.!?;:]", text):
            return True
    return False


def _document_index(document: Document) -> tuple[str, list[Block]]:
    counts: collections.Counter[str] = collections.Counter()
    headings: list[str] = []
    for block in document.blocks:
        if (block.metadata or {}).get("type") == "heading":
            headings.append(f"[{block.index}] {block.plain}")
        counts.update(word.lower() for word in _WORD_RE.findall(block.plain))
    repeated = {word for word, count in counts.items() if count >= 2}
    selected = [
        block for block in document.blocks
        if (block.metadata or {}).get("type") == "heading"
        or any(word.lower() in repeated for word in _WORD_RE.findall(block.plain))
    ]
    if not selected:
        selected = list(document.blocks)
    selected = selected[:MAX_CONSISTENCY_BLOCKS]
    terms = ", ".join(f"{word}:{count}" for word, count in counts.most_common(80) if count >= 2)
    index = "Заголовки:\n" + "\n".join(headings[:40]) + "\nПовторяющиеся термины:\n" + terms
    return index, selected


def _retrieval_result(value, count: int) -> tuple[list[list[dict]], dict]:
    if hasattr(value, "rules") and hasattr(value, "diagnostics"):
        return value.rules, value.diagnostics
    if isinstance(value, tuple) and len(value) == 2:
        rules, diagnostics = value
        return rules, diagnostics if isinstance(diagnostics, dict) else {}
    if isinstance(value, dict) and "rules" in value:
        rules = value.get("rules") or []
        return rules, value.get("diagnostics") or {}
    return value, {"mode": "legacy", "queries": count}


def _retrieve_batch(
    texts: list[str],
    guide: StyleGuide,
    task: str,
    k: int,
) -> tuple[list[list[dict]], dict]:
    task_api = getattr(rag, "retrieve_batch", None)
    if callable(task_api):
        return _retrieval_result(task_api(texts, guide, task=task, k=k), len(texts))
    task_batch_api = getattr(rag, "top_k_batch_for_task", None)
    if callable(task_batch_api):
        rules = task_batch_api(texts, guide, task=task, k=k)
        state_api = getattr(rag, "retrieval_state", None)
        diagnostics = state_api(guide) if callable(state_api) else {}
        diagnostics.update({"task": task, "queries": len(texts), "selected_k": k})
        return rules, diagnostics
    return _retrieval_result(rag.top_k_batch(texts, guide, k), len(texts))


def _retrieve_one(text: str, guide: StyleGuide, task: str, k: int = 10) -> tuple[list[dict], dict]:
    task_api = getattr(rag, "retrieve", None)
    if callable(task_api):
        value = task_api(text, guide, task=task, k=k)
        if hasattr(value, "rules") and hasattr(value, "diagnostics"):
            return value.rules, value.diagnostics
        if isinstance(value, tuple) and len(value) == 2:
            return value[0], value[1] if isinstance(value[1], dict) else {}
        if isinstance(value, dict) and "rules" in value:
            return value.get("rules") or [], value.get("diagnostics") or {}
        return value, {}
    return rag.top_k(text, guide, k), {"mode": "legacy"}


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    merged: dict[tuple, dict] = {}
    for candidate in candidates:
        key = (
            candidate.get("block_index"),
            candidate.get("rule_id"),
            str(candidate.get("span_text", "")).strip().lower(),
            str(candidate.get("suggestion", "")).strip().lower(),
        )
        if key not in merged:
            merged[key] = dict(candidate)
            continue
        current = merged[key]
        current["source_workers"] = sorted(
            set(current.get("source_workers", [])) | set(candidate.get("source_workers", []))
        )
        sources = {
            str(current.get("evidence_source", "")),
            str(candidate.get("evidence_source", "")),
        } - {""}
        current["evidence_source"] = "+".join(sorted(sources))
        current["verification_required"] = bool(
            current.get("verification_required", True)
            and candidate.get("verification_required", True)
        )
    return list(merged.values())


def _context_blocks(document: Document, candidates: list[dict]) -> list[Block]:
    positions = {block.index: pos for pos, block in enumerate(document.blocks)}
    wanted: set[int] = set()
    for candidate in candidates:
        pos = positions.get(candidate.get("block_index"))
        if pos is None:
            continue
        for block in document.blocks[max(0, pos - 1):pos + 2]:
            wanted.add(block.index)
    return [block for block in document.blocks if block.index in wanted]


def _resolve_conflicts(
    issues: list[dict],
    guide: StyleGuide,
) -> tuple[list[dict], list[dict]]:
    """Применяет заявленное старшинство правил и сообщает о конфликтах, где нужно решение человека."""
    dropped: set[int] = set()
    diagnostics: list[dict] = []
    for left_index, left in enumerate(issues):
        if left_index in dropped:
            continue
        left_rule = guide.get_rule(left.get("rule_id", "")) or {}
        left_rel = left_rule.get("relationships") or {}
        for right_index in range(left_index + 1, len(issues)):
            if right_index in dropped:
                continue
            right = issues[right_index]
            if left.get("block_index") != right.get("block_index"):
                continue
            right_rule = guide.get_rule(right.get("rule_id", "")) or {}
            right_rel = right_rule.get("relationships") or {}
            right_id = str(right.get("rule_id", ""))
            left_id = str(left.get("rule_id", ""))
            if right_id in set(left_rel.get("supersedes", [])) | set(
                left_rel.get("specializes", [])
            ):
                dropped.add(right_index)
                continue
            if left_id in set(right_rel.get("supersedes", [])) | set(
                right_rel.get("specializes", [])
            ):
                dropped.add(left_index)
                break
            family = str(left_rule.get("conflict_family") or "")
            explicit = (
                right_id in left_rel.get("conflicts", [])
                or left_id in right_rel.get("conflicts", [])
            )
            if not explicit and not (
                family and family == str(right_rule.get("conflict_family") or "")
            ):
                continue
            if left.get("suggestion") == right.get("suggestion"):
                continue
            left_key = rule_precedence_key(left_rule)
            right_key = rule_precedence_key(right_rule)
            diagnostics.append({
                "block_index": left.get("block_index"),
                "left_rule": left_id,
                "right_rule": right_id,
                "resolution": (
                    left_id if left_key < right_key else right_id if right_key < left_key
                    else "unresolved"
                ),
            })
            if left_key < right_key:
                dropped.add(right_index)
            elif right_key < left_key:
                dropped.add(left_index)
                break
    return [
        issue for index, issue in enumerate(issues) if index not in dropped
    ], diagnostics


async def run_pipeline_v2(
    document: Document,
    guide: StyleGuide,
    progress: ProgressCb | None = None,
    stream: StreamCb | None = None,
    options: dict | None = None,
) -> dict:
    selected = options or {}

    def enabled(stage: str) -> bool:
        if not _enabled(stage):
            return False
        category = {
            "language": "language",
            "evidence": "styleguide",
            "guide": "styleguide",
            "lexicon": "styleguide",
            "structure": "consistency",
            "terminology": "consistency",
            "consistency": "consistency",
        }.get(stage)
        return category is None or selected.get(category, True)

    def report_stage(stage: str) -> None:
        if progress:
            progress(stage)

    pass_seq = 0

    def open_pass(worker: int, scope: str):
        nonlocal pass_seq
        pass_seq += 1
        pass_id = pass_seq
        if stream:
            stream({
                "type": "start",
                "id": pass_id,
                "worker": WORKER_NAMES.get(worker, "Проверка"),
                "scope": scope,
            })

        def on_delta(text: str) -> None:
            if stream and text:
                stream({"type": "delta", "id": pass_id, "text": text})

        return pass_id, on_delta

    def close_pass(
        pass_id: int,
        status: str,
        found: int | None = None,
        error: str | None = None,
    ) -> None:
        if stream:
            event = {"type": "end", "id": pass_id, "status": status}
            if found is not None:
                event["found"] = found
            if error:
                event["error"] = error
            stream(event)

    if not document.blocks:
        return _empty_report(document.source, guide)

    stats = _Stats()
    stats.pipeline_version = "v2"
    report_stage("Подготовка структуры и правил")
    await asyncio.to_thread(rag.ensure_index, guide)

    chunk_size, overlap, run_consistency = _plan(len(document.blocks))
    chunks = chunk_blocks(document.blocks, chunk_size=chunk_size, overlap=overlap)
    if len(chunks) > MAX_CHUNKS_TARGET:
        logger.warning("v2 создал больше целевого числа фрагментов: %d", len(chunks))

    report_stage("Извлечение сигналов")
    engine_task = (
        asyncio.create_task(collect_engine_evidence(document, guide))
        if enabled("evidence")
        else None
    )
    lexicon_evidence = (
        collect_lexicon_evidence(document, guide) if enabled("lexicon") else []
    )

    query_texts = [chunk.plain() for chunk in chunks]
    guide_rules, guide_diag = await asyncio.to_thread(
        _retrieve_batch, query_texts, guide, "guide_local", 12
    )
    language_rules, language_diag = await asyncio.to_thread(
        _retrieve_batch, query_texts, guide, "language", 10
    )
    structure_rules, structure_diag = await asyncio.to_thread(
        _retrieve_batch, query_texts, guide, "structure", 12
    )

    # Сколько раз каждое правило было предложено воркерам: правило, которое
    # подбор ни разу не выдал, проверить нечем, и без этой диагностики это
    # не видно нигде.
    offered: collections.Counter[str] = collections.Counter()

    def _count_offered(batches) -> None:
        for batch in batches:
            offered.update(
                str(rule.get("rule_id", "")) for rule in batch if rule.get("rule_id")
            )

    _count_offered(guide_rules)
    _count_offered(language_rules)
    _count_offered(structure_rules)
    stats.retrieval = {
        "guide_local": guide_diag,
        "language": language_diag,
        "structure": structure_diag,
        "selected_rules": {
            "guide_local": sorted({
                rule.get("rule_id", "") for rules in guide_rules for rule in rules
            })[:100],
            "language": sorted({
                rule.get("rule_id", "") for rules in language_rules for rule in rules
            })[:100],
            "structure": sorted({
                rule.get("rule_id", "") for rules in structure_rules for rule in rules
            })[:100],
        },
        "rule_hit_counts": dict(offered.most_common()),
    }

    tasks: list[tuple[int, str, Callable]] = []
    for index, chunk in enumerate(chunks, 1):
        context = _chunk_context(document, chunk)
        scope = f"фрагмент {index} из {len(chunks)}"
        if enabled("language") and _has_prose(chunk):
            tasks.append((
                1,
                scope,
                lambda callback, c=chunk, r=language_rules[index - 1], x=context:
                    worker_language(guide, c, r, x, on_delta=callback),
            ))
        if enabled("guide"):
            tasks.append((
                4,
                scope,
                lambda callback, c=chunk, r=guide_rules[index - 1], x=context:
                    worker_guide_local(guide, c, r, x, on_delta=callback),
            ))
        if enabled("structure") and _has_structure(chunk):
            tasks.append((
                2,
                scope,
                lambda callback, c=chunk, r=structure_rules[index - 1], x=context:
                    worker_structure(guide, c, r, x, on_delta=callback),
            ))

    if len(document.blocks) >= 2 and (
        enabled("terminology") or enabled("consistency")
    ):
        document_index, consistency_blocks = _document_index(document)
        if enabled("terminology"):
            terminology_rules, terminology_diag = await asyncio.to_thread(
                _retrieve_one, document.full_plain(), guide, "terminology", 28
            )
            stats.retrieval["terminology"] = terminology_diag
            stats.retrieval["selected_rules"]["terminology"] = [
                rule.get("rule_id", "") for rule in terminology_rules
            ]
            _count_offered([terminology_rules])
            tasks.append((
                5,
                "документ",
                lambda callback, b=consistency_blocks, r=terminology_rules, x=document_index:
                    worker_terminology(guide, b, r, x, on_delta=callback),
            ))
        if enabled("consistency") and (
            run_consistency or len(document.blocks) >= MIN_BLOCKS_FOR_CONSISTENCY
        ):
            consistency_rules, consistency_diag = await asyncio.to_thread(
                _retrieve_one, document.full_plain(), guide, "consistency", 28
            )
            stats.retrieval["consistency"] = consistency_diag
            stats.retrieval["selected_rules"]["consistency"] = [
                rule.get("rule_id", "") for rule in consistency_rules
            ]
            _count_offered([consistency_rules])
            tasks.append((
                7,
                "документ",
                lambda callback, b=consistency_blocks, r=consistency_rules, x=document_index:
                    worker_consistency(guide, b, r, x, on_delta=callback),
            ))

    done = 0
    total = len(tasks)

    async def tracked(worker: int, scope: str, factory: Callable) -> list[dict]:
        nonlocal done
        stats.total += 1
        pass_id, on_delta = open_pass(worker, scope)
        started = time.monotonic()
        status = "done"
        found = 0
        worker_token = usage_stats.set_worker(WORKER_NAMES.get(worker, str(worker)))
        worker_name = WORKER_NAMES.get(worker, str(worker))
        try:
            issues = await _retry_pass(
                lambda: factory(on_delta),
                worker_name=worker_name,
                scope=scope,
            )
            found = len(issues)
            close_pass(pass_id, "done", len(issues))
            return issues
        except Exception as exc:  # noqa: BLE001
            status = "fail"
            message = _pass_error_message(exc)
            stats.failed += 1
            stats.last_error = message
            stats.failed_passes.append({
                "worker": worker_name,
                "scope": scope,
                "error": message,
            })
            logger.warning("v2-воркер завершился с ошибкой: %s", message)
            close_pass(pass_id, "fail", error=message)
            return []
        finally:
            usage_stats.reset_worker(worker_token)
            stats.pass_metrics.append({
                "worker": WORKER_NAMES.get(worker, str(worker)),
                "scope": scope,
                "status": status,
                "found": found,
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
            done += 1
            report_stage(f"Анализ: {done} из {total}")

    finder_results = await asyncio.gather(*(tracked(worker, scope, factory) for worker, scope, factory in tasks))
    try:
        engine_evidence = await engine_task if engine_task is not None else []
    except Exception as exc:  # noqa: BLE001
        stats.failed += 1
        stats.failed_passes.append({
            "worker": WORKER_NAMES[0],
            "scope": "документ",
            "error": str(exc),
        })
        engine_evidence = []

    candidates = _dedupe_candidates(
        [issue for batch in finder_results for issue in batch]
        + engine_evidence
        + lexicon_evidence
    )
    stats.candidates = len(candidates)
    stats.candidate_provenance = [
        {
            "block_index": candidate.get("block_index"),
            "rule_id": candidate.get("rule_id"),
            "source_workers": candidate.get("source_workers", []),
            "evidence_source": candidate.get("evidence_source", "llm"),
            "verification_required": candidate.get("verification_required", True),
        }
        for candidate in candidates
    ]
    if stats.total and stats.failed == stats.total and not engine_evidence:
        raise RuntimeError(f"Все v2-воркеры завершились ошибкой: {stats.last_error}")

    accepted = [
        candidate for candidate in candidates
        if not candidate.get("verification_required", True)
    ]
    for candidate in accepted:
        candidate["verification_status"] = "objective"

    to_verify = [
        candidate for candidate in candidates
        if candidate.get("verification_required", True)
    ]
    to_verify.sort(key=lambda item: (
        str((guide.get_rule(item.get("rule_id", "")) or {}).get("group", "")),
        item.get("block_index", 0),
    ))
    batches = [
        to_verify[index:index + VERIFY_BATCH]
        for index in range(0, len(to_verify), VERIFY_BATCH)
    ]

    async def verify_batch(index: int, batch: list[dict]) -> list[dict]:
        context_blocks = _context_blocks(document, batch)
        scope = f"батч {index} из {len(batches)}" if len(batches) > 1 else ""
        pass_id, on_delta = open_pass(6, scope)
        stats.total += 1
        started = time.monotonic()
        worker_token = usage_stats.set_worker(WORKER_NAMES[6])
        worker_name = WORKER_NAMES[6]
        try:
            verified, outcomes = await _retry_pass(
                lambda: worker_verifier(guide, context_blocks, batch, on_delta=on_delta),
                worker_name=worker_name,
                scope=scope,
            )
            stats.verifier_outcomes.extend(outcomes)
            close_pass(pass_id, "done", len(verified))
            stats.pass_metrics.append({
                "worker": worker_name,
                "scope": scope,
                "status": "done",
                "found": len(verified),
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
            return verified
        except Exception as exc:  # noqa: BLE001
            message = _pass_error_message(exc)
            stats.failed += 1
            stats.failed_passes.append({
                "worker": worker_name,
                "scope": scope,
                "error": message,
            })
            close_pass(pass_id, "fail", error=message)
            stats.pass_metrics.append({
                "worker": worker_name,
                "scope": scope,
                "status": "fail",
                "found": 0,
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
            logger.warning("v2-верификатор завершился с ошибкой: %s", message)
            return []
        finally:
            usage_stats.reset_worker(worker_token)

    report_stage("Проверка найденных замечаний")
    if enabled("verifier"):
        verified_batches = await asyncio.gather(*(
            verify_batch(index, batch) for index, batch in enumerate(batches, 1)
        ))
        verified = [issue for batch in verified_batches for issue in batch]
    else:
        verified = []
        for candidate in to_verify:
            candidate["verification_status"] = "ablation_unverified"
            verified.append(candidate)
        stats.retrieval["ablation"] = {
            "enabled_stages": os.getenv("PIPELINE_V2_STAGES", ""),
            "warning": "verifier disabled; output is evaluation-only",
        }
    final, stats.conflicts = _resolve_conflicts(_dedupe(accepted + verified), guide)
    stats.critic_dropped = max(0, len(candidates) - len(final))

    # Правила, которые подбор ни разу не предложил ни одному воркеру.
    never_offered = sorted(
        rule.get("rule_id", "") for rule in guide.rules
        if rule.get("rule_id") and offered.get(str(rule.get("rule_id")), 0) == 0
    )
    stats.retrieval["rules_total"] = len(guide.rules)
    stats.retrieval["rules_never_offered_count"] = len(never_offered)
    stats.retrieval["rules_never_offered"] = never_offered[:50]

    report_stage("Готово")
    return _build_report(document, guide, final, stats)

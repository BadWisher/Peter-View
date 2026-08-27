"""Оркестратор LLM-вычитки.

Воркеры 1-4 работают по чанкам, воркер 5 — терминология по всему документу,
воркер 7 — согласованность по всему документу; все параллельно. Затем воркер 6
(критик) сводит их результаты батчами параллельно, сверяясь с оригиналом.
Вся работа привязана к конкретному стайл-гайду.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Callable

from . import rag, stats as usage_stats
from .chunking import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, chunk_blocks, compress
from .documents import Document
from .schemas import to_ui_issue, validate_final_issues
from .styleguide import StyleGuide
from .workers import (
    worker_1, worker_2, worker_3, worker_4, worker_5, worker_6, worker_7, worker_8,
)

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]
StreamCb = Callable[[dict], None]
TERMINOLOGY_TOP_K = 10
CRITIC_BATCH = 20

# Человекочитаемые названия воркеров для живого стриминга их вывода.
WORKER_NAMES = {
    1: "Грамотность",
    2: "Форматирование",
    3: "Стиль и тон",
    4: "Соответствие гайду",
    5: "Терминология",
    6: "Критик",
    7: "Согласованность",
    8: "Лексикон",
}

# Адаптация числа проходов под объём: короткому тексту не нужен проход на
# согласованность, длинному — укрупняем чанки, чтобы не плодить десятки проходов.
MIN_BLOCKS_FOR_CONSISTENCY = 8
MAX_CHUNKS_TARGET = 24


def _plan(num_blocks: int) -> tuple[int, int, bool]:
    """Возвращает (chunk_size, overlap, делать_проход_на_согласованность)."""
    run_consistency = num_blocks >= MIN_BLOCKS_FOR_CONSISTENCY
    chunk_size = DEFAULT_CHUNK_SIZE
    step = max(1, chunk_size - DEFAULT_OVERLAP)
    while math.ceil(num_blocks / step) > MAX_CHUNKS_TARGET and chunk_size < 28:
        chunk_size += 4
        step = max(1, chunk_size - DEFAULT_OVERLAP)
    return chunk_size, DEFAULT_OVERLAP, run_consistency


class _Stats:
    def __init__(self) -> None:
        self.total = 0
        self.failed = 0
        self.candidates = 0
        self.critic_dropped = 0
        self.last_error: str | None = None
        self.failed_passes: list[dict] = []
        self.verifier_outcomes: list[dict] = []
        self.retrieval: dict = {}
        self.pass_metrics: list[dict] = []
        self.validation_rejections: list[dict] = []
        self.candidate_provenance: list[dict] = []
        self.conflicts: list[dict] = []
        self.pipeline_version = "v1"


def _issue_keys(report: dict) -> set[tuple]:
    return {
        (
            issue.get("block_index", issue.get("line")),
            issue.get("rule_id", issue.get("rule")),
            str(issue.get("replacement", issue.get("suggestion", ""))).strip().lower(),
        )
        for issue in report.get("issues", [])
    }


async def run_pipeline(
    document: Document,
    guide: StyleGuide,
    progress: ProgressCb | None = None,
    stream: StreamCb | None = None,
    options: dict | None = None,
) -> dict:
    version = os.getenv("PIPELINE_VERSION", "v2").strip().lower()
    shadow = os.getenv("PIPELINE_SHADOW", "false").strip().lower() in {"1", "true", "yes", "on"}
    if version == "v2":
        from .pipeline_v2 import run_pipeline_v2

        primary = await run_pipeline_v2(document, guide, progress=progress, stream=stream, options=options)
        if shadow:
            secondary = await _run_pipeline_v1(document, guide)
    else:
        primary = await _run_pipeline_v1(document, guide, progress=progress, stream=stream)
        if shadow:
            from .pipeline_v2 import run_pipeline_v2

            secondary = await run_pipeline_v2(document, guide, options=options)

    if shadow:
        primary_keys = _issue_keys(primary)
        secondary_keys = _issue_keys(secondary)
        primary.setdefault("meta", {})["shadow_comparison"] = {
            "primary": version,
            "secondary": "v1" if version == "v2" else "v2",
            "primary_only": len(primary_keys - secondary_keys),
            "secondary_only": len(secondary_keys - primary_keys),
            "shared": len(primary_keys & secondary_keys),
        }
    return primary


async def _run_pipeline_v1(
    document: Document,
    guide: StyleGuide,
    progress: ProgressCb | None = None,
    stream: StreamCb | None = None,
) -> dict:

    def report_stage(stage: str) -> None:
        if progress:
            progress(stage)

    pass_seq = 0

    def open_pass(worker: int, scope: str):
        """Регистрирует новый проход воркера и возвращает (id, on_delta)."""
        nonlocal pass_seq
        pass_seq += 1
        pid = pass_seq
        if stream:
            stream({"type": "start", "id": pid, "worker": WORKER_NAMES.get(worker, "Проверка"), "scope": scope})

        def on_delta(text: str) -> None:
            if stream and text:
                stream({"type": "delta", "id": pid, "text": text})

        return pid, on_delta

    def close_pass(pid: int, status: str, found: int | None = None, error: str | None = None) -> None:
        if stream:
            ev = {"type": "end", "id": pid, "status": status}
            if found is not None:
                ev["found"] = found
            if error:
                ev["error"] = error
            stream(ev)

    blocks = document.blocks
    if not blocks:
        return _empty_report(document.source, guide)

    report_stage("Подготовка правил")
    await asyncio.to_thread(rag.ensure_index, guide)

    chunk_size, overlap, run_consistency = _plan(len(blocks))
    chunks = chunk_blocks(blocks, chunk_size=chunk_size, overlap=overlap)

    # Правила для всех фрагментов подбираем одним пакетным обращением к эмбеддингам
    # (а не по запросу на фрагмент последовательно): иначе один подвисший запрос
    # морозил старт воркеров. term_rules — отдельным запросом (другой top-k).
    report_stage("Подбор правил")
    chunk_rules = await asyncio.to_thread(rag.top_k_batch, [c.plain() for c in chunks], guide)
    term_rules = await asyncio.to_thread(rag.top_k, document.full_plain(), guide, TERMINOLOGY_TOP_K)

    report_stage(f"Анализ фрагментов: 0 из {len(chunks)}")

    # Каждый проход — отдельный поток вывода воркера. Фабрика создаётся с
    # привязкой аргументов через значения по умолчанию (иначе замыкание поймает
    # последний chunk цикла).
    tasks: list[tuple[int, str, Callable]] = []
    for i, chunk in enumerate(chunks, 1):
        rules = chunk_rules[i - 1]
        chunk_ids = {b.index for b in chunk.blocks}
        context = compress([b for b in blocks if b.index not in chunk_ids])
        scope = f"фрагмент {i} из {len(chunks)}"

        tasks.append((1, scope, lambda od, c=chunk, r=rules: worker_1(guide, c, r, on_delta=od)))
        tasks.append((2, scope, lambda od, c=chunk, r=rules: worker_2(guide, c, r, on_delta=od)))
        tasks.append((3, scope, lambda od, c=chunk, x=context: worker_3(guide, c, x, on_delta=od)))
        tasks.append((4, scope, lambda od, c=chunk, x=context: worker_4(guide, c, x, on_delta=od)))

    tasks.append((5, "весь документ", lambda od: worker_5(guide, blocks, term_rules, on_delta=od)))
    if run_consistency:
        tasks.append((7, "весь документ", lambda od: worker_7(guide, blocks, term_rules, on_delta=od)))
    # Этап «Лексикон» добавляем, только если в гайде есть запрещённые выражения.
    if guide.lexicon_forbidden:
        tasks.append((8, "весь документ", lambda od: worker_8(guide, blocks, on_delta=od)))

    stats = _Stats()
    done = 0
    total = len(tasks)

    async def tracked(worker: int, scope: str, factory: Callable) -> list[dict]:
        nonlocal done
        stats.total += 1
        pid, on_delta = open_pass(worker, scope)
        started = time.monotonic()
        status = "done"
        found = 0
        worker_token = usage_stats.set_worker(WORKER_NAMES.get(worker, str(worker)))
        try:
            issues = await factory(on_delta)
            found = len(issues)
            close_pass(pid, "done", len(issues))
            return issues
        except Exception as e:  # noqa: BLE001
            status = "fail"
            stats.failed += 1
            stats.last_error = str(e)
            stats.failed_passes.append({
                "worker": WORKER_NAMES.get(worker, str(worker)),
                "scope": scope,
                "error": str(e),
            })
            logger.warning("Воркер завершился с ошибкой: %s", e)
            close_pass(pid, "fail", error=str(e))
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
            report_stage(f"Анализ: проверено {done} из {total} проходов")

    results = await asyncio.gather(*(tracked(w, s, f) for w, s, f in tasks))
    candidates = [issue for batch in results for issue in batch]
    stats.candidates = len(candidates)
    stats.candidate_provenance = [
        {
            "block_index": issue.get("block_index"),
            "rule_id": issue.get("rule_id"),
            "source_workers": issue.get("source_workers", []),
            "evidence_source": issue.get("evidence_source", "llm"),
        }
        for issue in _dedupe(candidates)
    ]
    logger.info("Собрано кандидатов от воркеров: %d", len(candidates))

    if stats.total and stats.failed == stats.total:
        raise RuntimeError(
            f"Все обращения к LLM завершились ошибкой, проверка не выполнена. "
            f"Последняя ошибка: {stats.last_error}"
        )

    report_stage("Критик перепроверяет замечания")
    final = await _critique(guide, blocks, candidates, open_pass, close_pass)
    stats.critic_dropped = max(0, len(_dedupe(candidates)) - len(final))

    report_stage("Готово")
    return _build_report(document, guide, final, stats)


def _dedupe(issues: list[dict]) -> list[dict]:
    """Схлопывает одинаковые замечания (один блок + одно правило), объединяя воркеров."""
    merged: dict[tuple, dict] = {}
    for issue in issues:
        key = (issue["block_index"], issue["rule_id"])
        if key in merged:
            workers = set(merged[key]["source_workers"]) | set(issue.get("source_workers", []))
            merged[key]["source_workers"] = sorted(workers)
        else:
            merged[key] = dict(issue)
    return list(merged.values())


async def _critique(guide: StyleGuide, blocks, candidates: list[dict],
                    open_pass=None, close_pass=None) -> list[dict]:
    """Прогоняет критика батчами по кандидатам, батчи — параллельно.

    Критик получает только блоки, к которым относятся замечания батча. Если батч
    падает (например, по лимиту токенов), замечания не теряются: возвращаем их
    дедуплицированными напрямую.
    """
    if not candidates:
        return []

    candidates = _dedupe(candidates)
    batches = [candidates[i:i + CRITIC_BATCH] for i in range(0, len(candidates), CRITIC_BATCH)]
    multi = len(batches) > 1
    positions = {block.index: pos for pos, block in enumerate(blocks)}

    async def run_batch(idx: int, batch: list[dict]) -> list[dict]:
        referenced = {c["block_index"] for c in batch}
        context_ids = set(referenced)
        for block_index in referenced:
            pos = positions.get(block_index)
            if pos is None:
                continue
            context_ids.update(block.index for block in blocks[max(0, pos - 1):pos + 2])
        context_blocks = [b for b in blocks if b.index in context_ids]
        scope = f"батч {idx} из {len(batches)}" if multi else ""
        pid, on_delta = (open_pass(6, scope) if open_pass else (None, None))
        worker_token = usage_stats.set_worker(WORKER_NAMES[6])
        try:
            result = await worker_6(guide, context_blocks, batch, on_delta=on_delta)
            if close_pass and pid is not None:
                close_pass(pid, "done", len(result))
            return result
        except Exception as e:  # noqa: BLE001
            logger.warning("Критик упал на батче, оставляем замечания как есть: %s", e)
            if close_pass and pid is not None:
                close_pass(pid, "fail", error=str(e))
            return _dedupe(batch)
        finally:
            usage_stats.reset_worker(worker_token)

    results = await asyncio.gather(*(run_batch(i, b) for i, b in enumerate(batches, 1)))
    return _dedupe([issue for batch in results for issue in batch])


def _group_duplicates(ui_issues: list[dict]) -> list[dict]:
    """Схлопывает только настоящие дубли: одно место + ОДИНАКОВАЯ конкретная правка.

    Критик уже убирает повторы по (блок, правило). Здесь объединяем случай, когда два
    РАЗНЫХ правила на одном фрагменте предлагают дословно одинаковую замену — это
    визуальный дубль в таблице. Замечания без конкретной правки (пустой replacement)
    НЕ группируем: они почти всегда про разные вещи, и схлопывание их прячет находки.
    """
    groups: dict[tuple, dict] = {}
    result: list[dict] = []
    for issue in ui_issues:
        suggestion = (issue.get("replacement") or "").strip().lower()
        rule_id = issue.get("rule")
        if not suggestion:
            issue["dup_count"] = 1
            issue["grouped_rules"] = [rule_id] if rule_id else []
            result.append(issue)
            continue
        key = (issue.get("line"), suggestion)
        if key in groups:
            grp = groups[key]
            grp["dup_count"] += 1
            if rule_id and rule_id not in grp["grouped_rules"]:
                grp["grouped_rules"].append(rule_id)
        else:
            merged = dict(issue)
            merged["dup_count"] = 1
            merged["grouped_rules"] = [rule_id] if rule_id else []
            groups[key] = merged
            result.append(merged)
    return result


def _ui_block(block) -> dict:
    meta = block.metadata or {}
    payload = {
        "index": block.index,
        "text": block.plain,
        "type": meta.get("type", "paragraph"),
    }
    for key in ("level", "list_kind", "list_depth", "list_index", "formatting", "cells"):
        value = meta.get(key)
        if value not in (None, [], ""):
            payload[key] = value
    return payload


def _build_report(document: Document, guide: StyleGuide, issues: list[dict], stats: _Stats) -> dict:
    blocks_by_index = {b.index: b.plain for b in document.blocks}
    issues, rejected = validate_final_issues(issues, guide, blocks_by_index)
    stats.validation_rejections.extend(rejected)
    ui_issues = []
    for issue in issues:
        ui = to_ui_issue(issue, blocks_by_index)
        ui.update({
            "block_index": issue["block_index"],
            "type": issue["type"],
            "rule_id": issue["rule_id"],
            "description": issue["description"],
            "suggestion": issue["suggestion"],
            "span_text": issue.get("span_text", ""),
            "severity_llm": issue["severity"],
            "source_workers": issue["source_workers"],
            "evidence_source": issue.get("evidence_source", "llm"),
            "verification_status": issue.get("verification_status", ""),
        })
        ui_issues.append(ui)

    ui_issues = _group_duplicates(ui_issues)

    partial = stats.failed > 0
    report = {
        "document": document.source,
        "styleguide": {"id": guide.id, "name": guide.name},
        "summary": {
            "total": len(ui_issues),
            "errors": sum(1 for i in ui_issues if i["severity"] == "error"),
            "warnings": sum(1 for i in ui_issues if i["severity"] == "warning"),
            "suggestions": sum(1 for i in ui_issues if i["severity"] == "suggestion"),
            "blocker": sum(1 for i in ui_issues if i.get("severity_llm") == "blocker"),
            "suggestion": sum(1 for i in ui_issues if i.get("severity_llm") == "suggestion"),
            "minor": sum(1 for i in ui_issues if i.get("severity_llm") == "minor"),
        },
        "issues": ui_issues,
        "blocks": [_ui_block(block) for block in document.blocks],
        "pages_checked": 1,
        "partial": partial,
        "meta": {
            "complete": not partial,
            "pipeline_version": stats.pipeline_version,
            "passes_total": stats.total,
            "passes_failed": stats.failed,
            "candidates": stats.candidates,
            "critic_dropped": stats.critic_dropped,
            "failed_passes": stats.failed_passes,
            "verifier_outcomes": stats.verifier_outcomes,
            "retrieval": stats.retrieval,
            "pass_metrics": stats.pass_metrics,
            "validation_rejections": stats.validation_rejections,
            "candidate_provenance": stats.candidate_provenance,
            "conflicts": stats.conflicts,
        },
    }
    if partial:
        report["partial_message"] = (
            f"Проверка неполная: {stats.failed} из {stats.total} проходов не выполнено "
            f"(возможен лимит токенов LLM). Часть замечаний могла быть не найдена."
        )
    return report


def _empty_report(source: str, guide: StyleGuide) -> dict:
    return {
        "document": source,
        "styleguide": {"id": guide.id, "name": guide.name},
        "summary": {"total": 0, "errors": 0, "warnings": 0, "suggestions": 0,
                    "blocker": 0, "suggestion": 0, "minor": 0},
        "issues": [],
        "blocks": [],
        "pages_checked": 1,
        "partial": False,
        "meta": {
            "complete": True,
            "pipeline_version": os.getenv("PIPELINE_VERSION", "v2"),
            "passes_total": 0,
            "passes_failed": 0,
            "candidates": 0,
            "critic_dropped": 0,
            "failed_passes": [],
            "verifier_outcomes": [],
            "retrieval": {},
            "pass_metrics": [],
            "validation_rejections": [],
            "candidate_provenance": [],
            "conflicts": [],
        },
    }

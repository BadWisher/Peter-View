"""Воркеры LLM-вычитки.

Воркеры 1-5 находят замечания на своих срезах документа, воркер 7 — проверка
согласованности по всему документу, воркер 6 — критик, который перепроверяет всё
по оригиналу. Все вызовы идут с temperature 0 и привязаны к выбранному стайл-гайду.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import styleguide
from .chunking import Chunk
from .client import complete_json
from .documents import Block
from .schemas import parse_worker_issues
from .styleguide import StyleGuide

logger = logging.getLogger(__name__)

PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1")
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts" / PROMPT_VERSION

_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)

_v2_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "prompts" / "v2")),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render(template: str, **ctx) -> str:
    return _env.get_template(template).render(**ctx)


def _render_v2(template: str, **ctx) -> str:
    return _v2_env.get_template(template).render(**ctx)


def _system(guide: StyleGuide) -> str:
    rendered = _render(
        "system_base.jinja2",
        general_rules=styleguide.general_rules_text(guide),
        base_rules=styleguide.base_rules_text(),
    )
    extra = str(getattr(guide, "extra_instruction", "") or "").strip()
    if extra:
        rendered += f"\n\nДополнительная инструкция пользователя:\n{extra}"
    return rendered + f"\n\nВерсия данных гайда: {_guide_cache_tag(guide)}"


def _system_v2(guide: StyleGuide) -> str:
    rendered = _render_v2(
        "system_base.jinja2",
        general_rules=styleguide.general_rules_text(guide),
        base_rules=styleguide.base_rules_text(),
    )
    extra = str(getattr(guide, "extra_instruction", "") or "").strip()
    if extra:
        rendered += f"\n\nДополнительная инструкция пользователя:\n{extra}"
    return rendered + f"\n\nВерсия данных гайда: {_guide_cache_tag(guide)}"


def _guide_cache_tag(guide: StyleGuide) -> str:
    payload = json.dumps(
        {
            "rules": guide.rules,
            "lexicon": guide.lexicon,
            "extra_instruction": getattr(guide, "extra_instruction", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    if getattr(guide, "extra_instruction", ""):
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return guide.content_hash or hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _label(blocks: list[Block], attr: str) -> str:
    lines = []
    for b in blocks:
        value = getattr(b, attr)
        if value:
            lines.append(f"[{b.index}] {value}")
    return "\n".join(lines)


def _structured_label(blocks: list[Block], max_chars: int = 16_000) -> str:
    lines: list[str] = []
    for block in blocks:
        renderer = getattr(block, "structured", None)
        if callable(renderer):
            value = renderer()
        else:
            meta = json.dumps(block.metadata or {}, ensure_ascii=False, sort_keys=True)
            value = f"<block id={block.index} metadata={meta}>{block.raw}</block>"
        if sum(len(line) + 1 for line in lines) + len(value) > max_chars:
            lines.append(json.dumps({
                "truncated": True,
                "remaining_blocks": len(blocks) - len(lines),
            }, ensure_ascii=False))
            break
        lines.append(value)
    return "\n".join(lines)


def _format_rules(rules: list[dict]) -> str:
    return styleguide.format_rules(rules)


OnDelta = Callable[[str], None] | None


def _parse_v2(response: dict, worker: int, guide: StyleGuide, blocks: list[Block]) -> list[dict]:
    return parse_worker_issues(
        response,
        source_worker=worker,
        valid_ids=guide.effective_ids,
        valid_indices={block.index for block in blocks},
        blocks_by_index={block.index: block.plain for block in blocks},
        guide=guide,
    )


async def worker_language(
    guide: StyleGuide,
    chunk: Chunk,
    rules: list[dict],
    context: str,
    on_delta: OnDelta = None,
) -> list[dict]:
    user = _render_v2(
        "language.jinja2",
        rules=_format_rules(rules),
        context=context,
        chunk=_label(chunk.blocks, "plain"),
    )
    response = await complete_json(_system_v2(guide), user, on_delta=on_delta)
    return _parse_v2(response, 1, guide, chunk.blocks)


async def worker_guide_local(
    guide: StyleGuide,
    chunk: Chunk,
    rules: list[dict],
    context: str,
    on_delta: OnDelta = None,
) -> list[dict]:
    user = _render_v2(
        "guide_local.jinja2",
        rules=_format_rules(rules),
        context=context,
        chunk=_structured_label(chunk.blocks),
    )
    response = await complete_json(_system_v2(guide), user, on_delta=on_delta)
    return _parse_v2(response, 4, guide, chunk.blocks)


async def worker_structure(
    guide: StyleGuide,
    chunk: Chunk,
    rules: list[dict],
    context: str,
    on_delta: OnDelta = None,
) -> list[dict]:
    user = _render_v2(
        "structure.jinja2",
        rules=_format_rules(rules),
        context=context,
        chunk=_structured_label(chunk.blocks),
    )
    response = await complete_json(_system_v2(guide), user, on_delta=on_delta)
    return _parse_v2(response, 2, guide, chunk.blocks)


async def worker_consistency(
    guide: StyleGuide,
    blocks: list[Block],
    rules: list[dict],
    document_index: str,
    on_delta: OnDelta = None,
) -> list[dict]:
    user = _render_v2(
        "consistency.jinja2",
        rules=_format_rules(rules),
        document_index=document_index,
        document=_structured_label(blocks),
    )
    response = await complete_json(_system_v2(guide), user, on_delta=on_delta)
    return _parse_v2(response, 7, guide, blocks)


async def worker_terminology(
    guide: StyleGuide,
    blocks: list[Block],
    rules: list[dict],
    document_index: str,
    on_delta: OnDelta = None,
) -> list[dict]:
    user = _render_v2(
        "terminology.jinja2",
        rules=_format_rules(rules),
        document_index=document_index,
        document=_structured_label(blocks),
    )
    response = await complete_json(_system_v2(guide), user, on_delta=on_delta)
    return _parse_v2(response, 5, guide, blocks)


async def worker_verifier(
    guide: StyleGuide,
    blocks: list[Block],
    candidates: list[dict],
    on_delta: OnDelta = None,
) -> tuple[list[dict], list[dict]]:
    numbered: list[dict] = []
    for source_id, candidate in enumerate(candidates):
        payload = dict(candidate)
        payload["source_id"] = source_id
        payload["cited_rule"] = guide.get_rule(candidate.get("rule_id", "")) or {}
        numbered.append(payload)

    user = _render_v2(
        "verifier.jinja2",
        document=_structured_label(blocks, max_chars=32_000),
        candidates=json.dumps(numbered, ensure_ascii=False, indent=2),
    )
    response = await complete_json(_system_v2(guide), user, on_delta=on_delta)
    raw_verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
    accepted: list[dict] = []
    outcomes: list[dict] = []
    valid_indices = {block.index for block in blocks}
    blocks_by_index = {block.index: block.plain for block in blocks}

    for raw in raw_verdicts if isinstance(raw_verdicts, list) else []:
        if not isinstance(raw, dict):
            continue
        try:
            source_id = int(raw["source_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= source_id < len(candidates):
            continue
        verdict = str(raw.get("verdict", "")).strip().lower()
        if verdict not in {"accept", "reject", "revise", "insufficient_context"}:
            continue
        candidate = dict(candidates[source_id])
        outcomes.append({
            "source_id": source_id,
            "rule_id": candidate.get("rule_id"),
            "block_index": candidate.get("block_index"),
            "verdict": verdict,
            "reason": str(raw.get("reason", "")).strip(),
        })
        if verdict not in {"accept", "revise"}:
            continue
        if verdict == "revise":
            for field in ("severity", "description", "suggestion"):
                value = str(raw.get(field, "")).strip()
                if value:
                    candidate[field] = value
        candidate["verification_status"] = "verified"
        parsed = parse_worker_issues(
            {"issues": [candidate]},
            source_worker=6,
            valid_ids=guide.effective_ids,
            valid_indices=valid_indices,
            blocks_by_index=blocks_by_index,
            guide=guide,
        )
        if parsed:
            parsed[0]["source_workers"] = candidate.get("source_workers", [])
            parsed[0]["evidence_source"] = candidate.get("evidence_source", "llm")
            accepted.append(parsed[0])
    return accepted, outcomes


async def worker_1(guide: StyleGuide, chunk: Chunk, rules: list[dict], on_delta: OnDelta = None) -> list[dict]:
    user = _render(
        "worker_1.jinja2",
        rules=_format_rules(rules),
        glossary=styleguide.glossary_text(guide),
        chunk=_label(chunk.blocks, "plain"),
    )
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=1, valid_ids=guide.effective_ids)


async def worker_2(guide: StyleGuide, chunk: Chunk, rules: list[dict], on_delta: OnDelta = None) -> list[dict]:
    user = _render("worker_2.jinja2", rules=_format_rules(rules), chunk=_label(chunk.blocks, "raw"))
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=2, valid_ids=guide.effective_ids)


async def worker_3(guide: StyleGuide, chunk: Chunk, context: str, on_delta: OnDelta = None) -> list[dict]:
    user = _render("worker_3.jinja2", context=context, chunk=_label(chunk.blocks, "plain"))
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=3, valid_ids=guide.effective_ids)


async def worker_4(guide: StyleGuide, chunk: Chunk, context: str, on_delta: OnDelta = None) -> list[dict]:
    user = _render("worker_4.jinja2", context=context, chunk=_label(chunk.blocks, "raw"))
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=4, valid_ids=guide.effective_ids)


async def worker_5(guide: StyleGuide, blocks: list[Block], rules: list[dict], on_delta: OnDelta = None) -> list[dict]:
    user = _render("worker_5.jinja2", rules=_format_rules(rules), document=_label(blocks, "plain"))
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=5, valid_ids=guide.effective_ids)


async def worker_7(guide: StyleGuide, blocks: list[Block], rules: list[dict], on_delta: OnDelta = None) -> list[dict]:
    """Проверка согласованности: одинаковые правила должны применяться единообразно.

    Ищет места, где правило нарушено непоследовательно (например, точки в конце
    стоят не у всех однотипных элементов, термины названы по-разному).
    """
    user = _render(
        "worker_7.jinja2",
        rules=_format_rules(rules),
        document=_label(blocks, "plain"),
    )
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=7, valid_ids=guide.effective_ids)


async def worker_8(guide: StyleGuide, blocks: list[Block], on_delta: OnDelta = None) -> list[dict]:
    """Лексикон: ищет запрещённые выражения по всему документу с учётом контекста и словоформ.

    Не делает поиск по точному совпадению строки — это контекстный этап: модель сама
    решает, является ли вхождение нарушением, и подставляет каноничную замену. Список
    разрешённых выражений передаётся, чтобы гасить ложные срабатывания.
    """
    user = _render(
        "worker_8.jinja2",
        forbidden=styleguide.forbidden_text(guide),
        allowed=styleguide.allowed_text(guide),
        document=_label(blocks, "plain"),
    )
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return parse_worker_issues(response, source_worker=8, valid_ids=guide.effective_ids)


async def worker_6(guide: StyleGuide, blocks: list[Block], candidates: list[dict], on_delta: OnDelta = None) -> list[dict]:
    """Критик: получает кандидатов и оригинал, возвращает вычищенный список.

    Кандидаты передаются пронумерованными; критик ссылается на них через source_ids,
    по которым восстанавливаем, из каких воркеров пришло итоговое замечание.
    """
    numbered = []
    for i, issue in enumerate(candidates):
        numbered.append({
            "source_id": i,
            "block_index": issue["block_index"],
            "type": issue["type"],
            "severity": issue["severity"],
            "rule_id": issue["rule_id"],
            "reasoning": issue.get("reasoning", ""),
            "description": issue["description"],
            "suggestion": issue["suggestion"],
            "span_text": issue.get("span_text", ""),
            "cited_rule": guide.get_rule(issue["rule_id"]) or {},
        })

    user = _render(
        "worker_6.jinja2",
        document=_label(blocks, "plain"),
        candidates=json.dumps(numbered, ensure_ascii=False, indent=2),
    )
    response = await complete_json(_system(guide), user, on_delta=on_delta)
    return _reconstruct_final(
        response,
        candidates,
        guide.effective_ids,
        {block.index for block in blocks},
    )


def _reconstruct_final(
    response: dict,
    candidates: list[dict],
    valid_ids: set[str],
    valid_indices: set[int] | None = None,
) -> list[dict]:
    final = []
    issues = response.get("issues", []) if isinstance(response, dict) else []

    for raw in issues:
        if not isinstance(raw, dict):
            continue
        rule_id = str(raw.get("rule_id", "")).strip()
        description = str(raw.get("description", "")).strip()
        if not rule_id or rule_id not in valid_ids or not description:
            continue

        source_workers: set[int] = set()
        source_candidates: list[dict] = []
        for sid in raw.get("source_ids", []) or []:
            if isinstance(sid, int) and 0 <= sid < len(candidates):
                source_workers.update(candidates[sid]["source_workers"])
                source_candidates.append(candidates[sid])
        if not source_candidates:
            continue

        severity = str(raw.get("severity", "")).strip().lower()
        if severity not in {"blocker", "suggestion", "minor"}:
            severity = "suggestion"

        try:
            block_index = int(raw["block_index"])
        except (TypeError, ValueError):
            continue
        except KeyError:
            continue
        if valid_indices is not None and block_index not in valid_indices:
            continue

        final.append({
            "block_index": block_index,
            "type": str(raw.get("type", "")).strip() or "style",
            "severity": severity,
            "rule_id": rule_id,
            "description": description,
            "suggestion": str(raw.get("suggestion", "")).strip(),
            "reasoning": str(raw.get("reasoning", "")).strip() or next(
                (str(item.get("reasoning", "")).strip() for item in source_candidates
                 if item.get("reasoning")),
                "",
            ),
            "span_text": next(
                (str(item.get("span_text", "")).strip() for item in source_candidates
                 if item.get("span_text")),
                "",
            ),
            "source_workers": sorted(source_workers),
            "evidence_source": "+".join(sorted({
                str(item.get("evidence_source", "llm")) for item in source_candidates
            })) or "llm",
            "verification_status": "verified",
        })

    return final

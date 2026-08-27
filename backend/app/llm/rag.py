"""Поиск релевантных правил стайл-гайда по тексту чанка (RAG).

Эмбеддинги считаются удалённым OpenAI-совместимым эндпоинтом (отдельным от LLM).
Правил немного (десятки), поэтому индекс держим прямо в памяти и считаем косинусную
близость через numpy — это надёжнее и проще внешнего векторного хранилища.

Индексы хранятся на каждый стайл-гайд (ключ — id гайда), перестраиваются при смене
содержимого (content_hash). Если эмбеддинги недоступны, поиск деградирует до выдачи
всех правил гайда.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from openai import OpenAI

from . import settings as llm_settings
from .styleguide import StyleGuide, rule_precedence_key, rule_priority

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 6
EMBED_TIMEOUT = float(os.getenv("EMBED_TIMEOUT", "20"))
# У эмбеддинг-эндпоинтов бывает лимит на число текстов в одном запросе
# (у Gemini, например, 100). Делим пачку на части, иначе индексы гайдов
# крупнее ~30 правил не строятся вовсе.
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "90"))

_lock = threading.Lock()
_embed_client: OpenAI | None = None


def _reset() -> None:
    """Сбрасывает клиент эмбеддингов и индексы при смене настроек."""
    global _embed_client, _indexes, _states
    with _lock:
        _embed_client = None
        _indexes = {}
        _states = {}


llm_settings.register_listener(_reset)


@dataclass
class _Index:
    content_hash: str
    rules: list[dict]
    lexical: list[Counter[str]]
    matrices: dict[str, np.ndarray] | None = None


@dataclass
class RetrievalResult:
    rules: list[dict]
    diagnostics: dict


@dataclass
class _GuideState:
    content_hash: str
    status: str
    error: str = ""
    updated_at: float = 0.0


_indexes: dict[str, _Index] = {}
_states: dict[str, _GuideState] = {}

_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
_RU_SUFFIXES = (
    "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ение", "ений",
    "ать", "ять", "ить", "ого", "ами", "ями", "ов", "ев", "ей", "ий", "ый",
    "ая", "яя", "ое", "ее", "ые", "ие", "ам", "ям", "ах", "ях", "ом", "ем",
    "у", "ю", "а", "я", "ы", "и", "е", "о",
)


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(str(text).lower().replace("ё", "е")):
        tokens.append(token)
        if len(token) > 5:
            stem = next(
                (token[:-len(suffix)] for suffix in _RU_SUFFIXES
                 if token.endswith(suffix) and len(token) - len(suffix) >= 3),
                token,
            )
            if stem != token:
                tokens.append(stem)
    return tokens


def _join(values: Iterable) -> str:
    return " ".join(str(value) for value in values if value)


def _rule_documents(rule: dict) -> dict[str, str]:
    return {
        "identity": _join([
            rule.get("title", ""), rule.get("section", ""), rule.get("group", ""),
            *(rule.get("categories", []) or []),
        ]),
        "policy": _join([
            rule.get("rule", ""), rule.get("generalization", ""),
        ]),
        "examples": _join([
            *(rule.get("bad_examples", []) or []),
            *(rule.get("good_examples", []) or []),
        ]),
    }


def _rule_document(rule: dict) -> str:
    parts = _rule_documents(rule).values()
    return " ".join(p for p in parts if p)


def _get_embed_client() -> OpenAI:
    global _embed_client
    if _embed_client is None:
        api_key = llm_settings.get_value("embedding_api_key")
        if not api_key:
            raise RuntimeError("Ключ эмбеддингов не задан, укажите его в настройках проверки")
        # Короткий таймаут и без долгих ретраев: эндпоинт эмбеддингов иногда
        # подвисает, а из-за подбора правил это морозило всю проверку на этапе
        # «Анализ фрагментов: 0 из N». Лучше быстро упасть и деградировать на
        # «все правила», чем ждать минуту на каждый зависший запрос.
        _embed_client = OpenAI(
            base_url=llm_settings.get_value("embedding_base_url"),
            api_key=api_key,
            timeout=EMBED_TIMEOUT,
            max_retries=0,
        )
    return _embed_client


def _embed(texts: list[str]) -> np.ndarray:
    model = llm_settings.get_value("embedding_model")
    client = _get_embed_client()
    chunks = [texts[i:i + EMBED_BATCH_SIZE] for i in range(0, len(texts), EMBED_BATCH_SIZE)]
    vectors = []
    for chunk in chunks:
        resp = client.embeddings.create(model=model, input=chunk)
        vectors.extend(item.embedding for item in resp.data)
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"эмбеддинг-эндпоинт вернул {len(vectors)} векторов на {len(texts)} текстов"
        )
    matrix = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _build_index(guide: StyleGuide) -> None:
    if not guide.rules:
        _indexes[guide.id] = _Index(guide.content_hash, [], [])
        _states[guide.id] = _GuideState(guide.content_hash, "empty", updated_at=time.time())
        return
    rules = list(guide.rules)
    lexical = [Counter(_tokens(_rule_document(rule))) for rule in rules]
    matrices: dict[str, np.ndarray] | None = None
    error = ""
    try:
        field_names = ("identity", "policy", "examples")
        documents = [_rule_documents(rule) for rule in rules]
        vectors = _embed([
            documents[index][field] or field
            for field in field_names
            for index in range(len(rules))
        ])
        matrices = {
            field: vectors[offset * len(rules):(offset + 1) * len(rules)]
            for offset, field in enumerate(field_names)
        }
        status = "hybrid"
    except Exception as e:  # noqa: BLE001
        status = "lexical_only"
        error = str(e)
        logger.warning("Семантический индекс гайда %s недоступен: %s", guide.id, e)
    _indexes[guide.id] = _Index(guide.content_hash, rules, lexical, matrices)
    _states[guide.id] = _GuideState(guide.content_hash, status, error, time.time())
    logger.info("RAG-индекс построен для гайда %s: %d правил, режим %s",
                guide.id, len(rules), status)


def ensure_index(guide: StyleGuide) -> None:
    """Строит индекс гайда при первом обращении и перестраивает при смене правил."""
    with _lock:
        existing = _indexes.get(guide.id)
        if existing is not None and existing.content_hash == guide.content_hash:
            return
        try:
            _build_index(guide)
        except Exception as e:  # noqa: BLE001
            _states[guide.id] = _GuideState(
                guide.content_hash, "fallback", str(e), time.time(),
            )
            logger.warning("Индекс гайда %s недоступен, используется фоллбэк: %s", guide.id, e)


def healthcheck() -> None:
    if not str(llm_settings.get_value("embedding_base_url") or "").strip():
        raise RuntimeError("Эмбеддинги не настроены")
    _embed(["ping"])


def _lexical_scores(text: str, index: _Index) -> np.ndarray:
    query = Counter(_tokens(text))
    scores = np.zeros(len(index.rules), dtype=np.float32)
    if not query:
        return scores
    for i, document in enumerate(index.lexical):
        overlap = sum(min(count, document.get(token, 0)) for token, count in query.items())
        scores[i] = overlap / max(1.0, sum(query.values()) ** 0.5 * sum(document.values()) ** 0.5)
        lowered = text.casefold().replace("ё", "е")
        if any(
            str(example).casefold().replace("ё", "е") in lowered
            for example in index.rules[i].get("bad_examples", []) or []
            if len(str(example).strip()) >= 3
        ):
            scores[i] += 1.0
    return scores


def _semantic_scores(query: np.ndarray, index: _Index) -> np.ndarray:
    if not index.matrices:
        return np.zeros(len(index.rules), dtype=np.float32)
    return (
        0.25 * (index.matrices["identity"] @ query)
        + 0.45 * (index.matrices["policy"] @ query)
        + 0.30 * (index.matrices["examples"] @ query)
    )


def _metadata_boost(rule: dict, task: str | None, categories: Iterable[str] | None,
                    scope: str | None) -> float:
    boost = rule_priority(rule) / 1000.0
    if task and task in (rule.get("tasks") or []):
        boost += 0.12
    requested_categories = set(categories or [])
    if requested_categories.intersection(rule.get("categories") or []):
        boost += 0.10
    rule_scope = str(rule.get("scope", "all"))
    if scope and rule_scope in ("all", scope):
        boost += 0.06
    if rule.get("machine_verifiable"):
        boost += 0.02
    return boost


def _select(index: _Index, scores: np.ndarray, k: int) -> list[dict]:
    mandatory = sorted(
        [i for i, rule in enumerate(index.rules) if rule.get("mandatory")],
        key=lambda i: rule_precedence_key(index.rules[i]),
    )
    if k <= 0:
        return [index.rules[i] for i in mandatory]
    ranked = sorted(
        range(len(index.rules)),
        key=lambda i: (-float(scores[i]), rule_precedence_key(index.rules[i])),
    )
    selected = list(mandatory)
    for i in ranked:
        if i not in selected:
            selected.append(i)
        if len(selected) >= max(k, len(mandatory)):
            break
    return [index.rules[i] for i in selected]


def retrieve(
    text: str,
    guide: StyleGuide,
    k: int = DEFAULT_TOP_K,
    *,
    task: str | None = None,
    categories: Iterable[str] | None = None,
    scope: str | None = None,
) -> RetrievalResult:
    """Гибридный поиск: обязательное ядро плюс релевантные правила, с диагностикой запроса."""
    ensure_index(guide)
    index = _indexes.get(guide.id)
    state = _states.get(guide.id)
    if index is None:
        rules = sorted(guide.rules, key=rule_precedence_key)
        return RetrievalResult(rules, {
            "guide_id": guide.id, "mode": "fallback", "semantic_used": False,
            "lexical_used": False, "error": state.error if state else "index unavailable",
            "fallback_tier": "all_rules",
        })

    lexical = _lexical_scores(text, index)
    scores = lexical * 0.55
    semantic_used = False
    request_error = ""
    if index.matrices:
        try:
            scores += _semantic_scores(_embed([text])[0], index) * 0.45
            semantic_used = True
        except Exception as e:  # noqa: BLE001
            request_error = str(e)
            logger.warning("Семантический RAG-запрос гайда %s не удался: %s", guide.id, e)
    for i, rule in enumerate(index.rules):
        scores[i] += _metadata_boost(rule, task, categories, scope)
    lexical_used = bool(np.any(lexical > 0))
    mode = "hybrid" if semantic_used else ("lexical" if lexical_used else "all_rules")
    selected = (
        _select(index, scores, max(0, k))
        if semantic_used or lexical_used
        else sorted(index.rules, key=rule_precedence_key)
    )
    return RetrievalResult(selected, {
        "guide_id": guide.id,
        "content_hash": guide.content_hash,
        "mode": mode,
        "semantic_used": semantic_used,
        "lexical_used": lexical_used,
        "fallback_tier": (
            "none" if semantic_used else ("lexical_mandatory" if lexical_used else "all_rules")
        ),
        "index_status": state.status if state else "unknown",
        "index_error": state.error if state else "",
        "request_error": request_error,
        "mandatory_count": sum(bool(rule.get("mandatory")) for rule in index.rules),
        "candidate_count": len(index.rules),
    })


def exact_rule(guide: StyleGuide, rule_id: str) -> dict | None:
    """Точное правило по id (из гайда, базовых или лексикона) без поиска."""
    return guide.get_rule(rule_id)


def retrieval_state(guide: StyleGuide) -> dict:
    """Состояние поиска по одному гайду, не трогая индексы остальных."""
    ensure_index(guide)
    state = _states.get(guide.id)
    return {
        **guide.retrieval_readiness,
        "guide_id": guide.id,
        "index_status": state.status if state else "unknown",
        "index_error": state.error if state else "",
        "fallback_tier": (
            "none"
            if state and state.status == "hybrid"
            else "lexical_mandatory"
            if state and state.status == "lexical_only"
            else "all_rules"
        ),
    }


def top_k(text: str, guide: StyleGuide, k: int = DEFAULT_TOP_K) -> list[dict]:
    """Backward-compatible hybrid retrieval entry point."""
    return retrieve(text, guide, k).rules


def top_k_for_task(
    text: str,
    guide: StyleGuide,
    *,
    task: str,
    k: int = DEFAULT_TOP_K,
    categories: Iterable[str] | None = None,
    scope: str | None = None,
) -> list[dict]:
    return retrieve(
        text, guide, k, task=task, categories=categories, scope=scope,
    ).rules


def top_k_batch(texts: list[str], guide: StyleGuide, k: int = DEFAULT_TOP_K) -> list[list[dict]]:
    """То же, что top_k, но для пачки запросов одним обращением к эмбеддингам.

    Подбор правил для всех фрагментов раньше шёл по одному запросу на фрагмент
    последовательно — при флакающем эндпоинте это морозило старт воркеров. Здесь
    эмбеддим все тексты разом (один сетевой вызов), а близость считаем локально.
    """
    if not texts:
        return []
    ensure_index(guide)
    index = _indexes.get(guide.id)
    if index is None:
        return [sorted(guide.rules, key=rule_precedence_key) for _ in texts]
    queries: np.ndarray | None = None
    if index.matrices:
        try:
            queries = _embed(texts)
        except Exception as e:  # noqa: BLE001
            logger.warning("Пакетный семантический RAG-запрос гайда %s не удался: %s", guide.id, e)
    out: list[list[dict]] = []
    for position, text in enumerate(texts):
        lexical = _lexical_scores(text, index)
        scores = lexical * 0.55
        if queries is not None:
            scores += _semantic_scores(queries[position], index) * 0.45
        for i, rule in enumerate(index.rules):
            scores[i] += _metadata_boost(rule, None, None, None)
        out.append(
            _select(index, scores, max(0, k))
            if queries is not None or np.any(lexical > 0)
            else sorted(index.rules, key=rule_precedence_key)
        )
    return out


def top_k_batch_for_task(
    texts: list[str],
    guide: StyleGuide,
    *,
    task: str,
    k: int = DEFAULT_TOP_K,
    categories: Iterable[str] | None = None,
    scope: str | None = None,
) -> list[list[dict]]:
    """Task-aware batch API; keeps request metadata as soft boosts."""
    if not texts:
        return []
    ensure_index(guide)
    index = _indexes.get(guide.id)
    if index is None:
        return [sorted(guide.rules, key=rule_precedence_key) for _ in texts]
    try:
        queries = _embed(texts) if index.matrices else None
    except Exception:  # noqa: BLE001
        queries = None
    output: list[list[dict]] = []
    for position, text in enumerate(texts):
        lexical = _lexical_scores(text, index)
        scores = lexical * 0.55
        if queries is not None:
            scores += _semantic_scores(queries[position], index) * 0.45
        for i, rule in enumerate(index.rules):
            scores[i] += _metadata_boost(rule, task, categories, scope)
        output.append(
            _select(index, scores, max(0, k))
            if queries is not None or np.any(lexical > 0)
            else sorted(index.rules, key=rule_precedence_key)
        )
    return output

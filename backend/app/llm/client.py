"""OpenAI-совместимый клиент. URL и ключ берутся из настроек администратора."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Callable

from openai import (
    AsyncOpenAI,
    APIError,
    APITimeoutError,
    BadRequestError,
    RateLimitError,
)

from . import settings as llm_settings
from . import stats

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
CACHE_MAX = 1024

_semaphore = asyncio.Semaphore(int(llm_settings.get_value("llm_concurrency")))
_client: AsyncOpenAI | None = None
_cache: dict[str, dict] = {}
# Что сервер не принял (response_format/reasoning_effort) — запоминаем, чтобы не
# слать повторно. Сбрасывается при смене настроек (новый сервер — новые возможности).
_unsupported: set[str] = set()


def _reset() -> None:
    """Сбрасывает клиент/семафор/кэш при смене настроек."""
    global _client, _semaphore, _cache
    _client = None
    _semaphore = asyncio.Semaphore(int(llm_settings.get_value("llm_concurrency")))
    _cache = {}
    _unsupported.clear()


llm_settings.register_listener(_reset)


def _is_rate_limited(error: Exception) -> bool:
    """402 token_limit_exceeded у некоторых провайдеров — это минутный лимит квоты.

    Его, как и 429, имеет смысл повторять с паузой, а не падать сразу.
    """
    if getattr(error, "status_code", None) == 402:
        return True
    text = str(error).lower()
    return "token_limit" in text or "rate_limit" in text or "too many requests" in text


def _is_transient_api_error(error: Exception) -> bool:
    """Кратковременные сбои провайдера, которые имеет смысл повторить."""
    code = getattr(error, "status_code", None)
    if code in (502, 503, 504):
        return True
    text = str(error).lower()
    markers = (
        "abnormal",
        "incomplete or invalid json",
        "overloaded",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "try again",
    )
    return any(marker in text for marker in markers)


class LLMRequestError(RuntimeError):
    """Ошибка провайдера в безопасной для показа пользователю формулировке."""


def _public_error_message(error: Exception | None) -> str:
    """Короткая типизированная ошибка вместо сырого текста провайдера.

    Внутренние ответы API бывают многострочными и содержат фрагменты промпта,
    поэтому наружу уходит только класс проблемы; полный текст остаётся в журнале.
    """
    if error is None:
        return "Сервис проверки недоступен"
    if _is_rate_limited(error):
        return "Превышен лимит запросов к сервису проверки, попробуйте позже"
    code = getattr(error, "status_code", None)
    if code in (401, 403):
        return "Сервис проверки отклонил ключ доступа, проверьте настройки"
    if code == 404:
        return "Модель или адрес сервиса не найдены, проверьте настройки"
    if isinstance(error, APITimeoutError):
        return f"Сервис проверки не ответил за {float(llm_settings.get_value('llm_timeout')):.0f}с"
    if isinstance(error, RateLimitError):
        return "Превышен лимит запросов к сервису проверки, попробуйте позже"
    if _is_transient_api_error(error):
        return "Сервис проверки временно недоступен, попробуйте ещё раз"
    if isinstance(error, json.JSONDecodeError):
        return "Сервис проверки вернул некорректный ответ, повторите проверку"
    return f"Ошибка сервиса проверки (код {code})" if code else "Сервис проверки недоступен"


def _cache_key(system: str, user: str, extra: str = "") -> str:
    model = llm_settings.get_value("llm_model")
    namespace = "\x00".join((
        os.getenv("PIPELINE_VERSION", "v2"),
        os.getenv("PROMPT_VERSION", "v1"),
        os.getenv("RAG_CONFIG_VERSION", "v1"),
        os.getenv("PIPELINE_V2_STAGES", ""),
        extra,
    ))
    return hashlib.sha256(
        f"{model}\x00{namespace}\x00{system}\x00{user}".encode("utf-8")
    ).hexdigest()

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _first_json_object(text: str) -> dict | None:
    """Находит первый сбалансированный JSON-объект в тексте.

    Рассуждающие модели часто пишут размышление до и после JSON — обычный json.loads
    на таком падает (Expecting value / Extra data). Сканируем по балансу скобок,
    учитывая строки и экранирование, и парсим первый цельный объект.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _extract_json(content: str) -> dict:
    """Достаёт JSON-объект из ответа модели, игнорируя обрамляющий текст и фенсы."""
    text = _THINK_RE.sub("", content).strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        obj = _first_json_object(text)
        if obj is not None:
            return obj
        raise


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = llm_settings.get_value("llm_api_key")
        if not api_key:
            raise RuntimeError("Ключ модели не задан – укажи его в настройках проверки")
        _client = AsyncOpenAI(
            base_url=llm_settings.get_value("llm_base_url"),
            api_key=api_key,
            timeout=float(llm_settings.get_value("llm_timeout")),
        )
    return _client


async def _create(
    client: AsyncOpenAI,
    messages: list[dict],
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
):
    """Вызов chat.completions с самовосстановлением под возможности сервера.

    Часть OpenAI-совместимых серверов (некоторые сборки vLLM/llama.cpp/Ollama) не
    принимают response_format или reasoning_effort и отвечают 400. Тогда мы по очереди
    отбрасываем эти параметры, запоминаем неподдержанное в _unsupported и больше его
    не шлём. Это даёт «работает из коробки» с gpt-oss и облачным OpenAI без правок кода.
    """
    base: dict = {
        "model": llm_settings.get_value("llm_model"),
        "messages": messages,
        "temperature": float(
            llm_settings.get_value("llm_temperature") if temperature is None else temperature
        ),
    }
    if max_tokens is not None:
        base["max_tokens"] = max_tokens

    want_json = "json" not in _unsupported and bool(llm_settings.get_value("llm_json_mode"))
    effort = "" if "reasoning" in _unsupported else str(
        llm_settings.get_value("llm_reasoning_effort") or ""
    ).strip()

    def build(use_json: bool, use_reasoning: bool) -> dict:
        kw = dict(base)
        if use_json:
            kw["response_format"] = {"type": "json_object"}
        if use_reasoning:
            kw["extra_body"] = {"reasoning_effort": effort}
        return kw

    # Пробуем максимально богатый вариант, затем деградируем: сначала без reasoning,
    # потом без json. Что сработало — запоминаем как (не)поддержанное.
    attempts: list[tuple[bool, bool]] = [(want_json, bool(effort))]
    if effort:
        attempts.append((want_json, False))
    if want_json:
        attempts.append((False, False))

    last: Exception | None = None
    for use_json, use_reasoning in attempts:
        try:
            resp = await client.chat.completions.create(**build(use_json, use_reasoning))
            if bool(effort) and not use_reasoning:
                _unsupported.add("reasoning")
                logger.warning("Сервер не принял reasoning_effort — отключаю его")
            if want_json and not use_json:
                _unsupported.add("json")
                logger.warning("Сервер не принял response_format — отключаю JSON-режим")
            return resp
        except BadRequestError as e:
            last = e
            continue
    raise last  # type: ignore[misc]


async def _create_stream(client: AsyncOpenAI, messages: list[dict], on_delta: Callable[[str], None]):
    """Стриминговый вызов: дёргает on_delta на каждый токен (рассуждение + ответ).

    Возвращает (полный_текст_ответа, usage|None). Логика деградации параметров та
    же, что в _create. Если сервер не умеет стриминг — пусть падает BadRequestError,
    а вызывающий код откатится на обычный _create.
    """
    base: dict = {
        "model": llm_settings.get_value("llm_model"),
        "messages": messages,
        "temperature": float(llm_settings.get_value("llm_temperature")),
        "stream": True,
    }
    effort = "" if "reasoning" in _unsupported else str(
        llm_settings.get_value("llm_reasoning_effort") or ""
    ).strip()

    def build(use_reasoning: bool) -> dict:
        kw = dict(base)
        if use_reasoning:
            kw["extra_body"] = {"reasoning_effort": effort}
        return kw

    # json_object и stream_options.include_usage на стриме часто заставляют
    # провайдера (в т.ч. Qwen) отдать весь ответ одним куском в конце и
    # выключить канал рассуждений. JSON вытаскиваем из полного текста после.
    attempts = [True] if effort else [False]
    if effort:
        attempts.append(False)

    last: Exception | None = None
    for use_reasoning in attempts:
        try:
            stream = await client.chat.completions.create(**build(use_reasoning))
        except BadRequestError as e:
            last = e
            continue
        content_buf = ""
        shown = 0
        json_started = False
        usage = None
        async for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                usage = chunk.usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta
            if delta is None:
                continue
            reasoning = _delta_text(delta, "reasoning_content", "reasoning")
            if reasoning:
                on_delta(reasoning)
            piece = _delta_text(delta, "content")
            if not piece:
                continue
            content_buf += piece
            # В лог воркера идёт живая речь: рассуждение до JSON/фенса.
            # Сам JSON служебный, его показывали целиком после окончания письма.
            if not json_started:
                marks = [p for p in (content_buf.find("{"), content_buf.find("```")) if p != -1]
                idx = min(marks) if marks else -1
                limit = len(content_buf) if idx == -1 else idx
                if idx != -1:
                    json_started = True
                if limit > shown:
                    on_delta(content_buf[shown:limit])
                    shown = limit
        if bool(effort) and not use_reasoning:
            _unsupported.add("reasoning")
            logger.warning("Сервер не принял reasoning_effort — отключаю его")
        return content_buf, usage
    raise last  # type: ignore[misc]


def _delta_text(delta, *names: str) -> str:
    extra = getattr(delta, "model_extra", None)
    extra = extra if isinstance(extra, dict) else {}
    for name in names:
        value = getattr(delta, name, None)
        if value is None:
            value = extra.get(name)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str) and item:
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "".join(parts)
    return ""


async def complete_json(
    system: str,
    user: str,
    on_delta: Callable[[str], None] | None = None,
    *,
    temperature: float | None = None,
) -> dict:
    """Один вызов модели в JSON-режиме. Возвращает разобранный объект.

    При временных ошибках провайдера (в т.ч. минутный лимит токенов 402) повторяет
    запрос с экспоненциальной паузой. Результаты кэшируются по содержимому запроса —
    одинаковый промпт (тот же текст и правила) не гоняется в модель повторно.

    Если передан on_delta — в колбэк идут токены живой речи воркера (рассуждение),
    а не готовый JSON.
    """
    key = _cache_key(system, user, extra=f"t{temperature}" if temperature is not None else "")
    cached = _cache.get(key)
    if cached is not None:
        return cached
    # Персистентный кэш переживает рестарт: одинаковый промпт не гоняем в модель
    # повторно даже между запусками (экономия токенов).
    persisted = stats.cache_get(key)
    if persisted is not None:
        _cache[key] = persisted
        return persisted

    client = _get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_error: Exception | None = None
    async with _semaphore:
        for attempt in range(MAX_RETRIES):
            content = ""
            try:
                if on_delta is not None:
                    try:
                        content, usage = await _create_stream(client, messages, on_delta)
                    except BadRequestError:
                        # Сервер не умеет стриминг — деградируем до обычного вызова.
                        resp = await _create(client, messages, temperature=temperature)
                        content = resp.choices[0].message.content or ""
                        usage = getattr(resp, "usage", None)
                else:
                    resp = await _create(client, messages, temperature=temperature)
                    content = resp.choices[0].message.content or ""
                    usage = getattr(resp, "usage", None)
                result = _extract_json(content)
                if usage is not None:
                    # У части провайдеров счётчик кэшированных префиксов живёт
                    # в prompt_tokens_details, у других отсутствует вовсе.
                    details = getattr(usage, "prompt_tokens_details", None)
                    cached = getattr(details, "cached_tokens", None) if details else None
                    stats.record_tokens(
                        getattr(usage, "prompt_tokens", 0) or 0,
                        getattr(usage, "completion_tokens", 0) or 0,
                        cached_tokens=cached or 0,
                    )
                if len(_cache) >= CACHE_MAX:
                    _cache.pop(next(iter(_cache)))
                _cache[key] = result
                stats.cache_set(key, result)
                return result
            except (RateLimitError, APITimeoutError) as e:
                last_error = e
                wait = min(30, 3 * (2 ** attempt))
                logger.warning("LLM повтор через %ds (попытка %d): %s", wait, attempt + 1, e)
                await asyncio.sleep(wait)
            except json.JSONDecodeError as e:
                last_error = e
                # Не логируем содержимое ответа: туда могут попасть фрагменты
                # документа. Достаточно факта и длины.
                logger.warning("LLM вернул невалидный JSON (попытка %d): %s | длина ответа: %d",
                               attempt + 1, e, len(content))
                await asyncio.sleep(1)
            except APIError as e:
                last_error = e
                if _is_rate_limited(e):
                    wait = min(45, 5 * (2 ** attempt))
                    logger.warning("LLM лимит токенов, повтор через %ds (попытка %d): %s",
                                   wait, attempt + 1, e)
                    await asyncio.sleep(wait)
                    continue
                if _is_transient_api_error(e):
                    wait = min(30, 3 * (2 ** attempt))
                    logger.warning("LLM временная ошибка, повтор через %ds (попытка %d): %s",
                                   wait, attempt + 1, e)
                    await asyncio.sleep(wait)
                    continue
                logger.error("Ошибка LLM API: %s", e)
                break

    raise LLMRequestError(_public_error_message(last_error))


async def healthcheck() -> None:
    if not str(llm_settings.get_value("llm_base_url") or "").strip():
        raise RuntimeError("LLM не настроен")
    client = _get_client()
    async with _semaphore:
        # Простой вызов без JSON-режима: при response_format=json_object OpenAI требует
        # слово «json» в промпте, а нам тут это ни к чему. 16 токенов — потому что
        # reasoning-модели (gpt-oss) часть бюджета тратят на рассуждение.
        await client.chat.completions.create(
            model=llm_settings.get_value("llm_model"),
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=16,
            temperature=0,
        )

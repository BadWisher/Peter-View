from __future__ import annotations

import asyncio
import copy
import os
import json
import logging
import re
import secrets
import threading
import time
import uuid

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import audit
from . import auth
from . import backups
from . import features
from . import oidc as oidc_login
from .auth import require_admin, require_user
from .checker import check_text
from .crawler import crawl_site
from .extractors import extract_from_file
from .report import generate_excel_report
from .style_guide_registry import get_registry
from .llm import jobs as llm_jobs
from .llm import extract_jobs
from .llm import styleguide_store
from .llm import settings as llm_settings
from .llm import client as llm_client
from .llm import rag as llm_rag
from .llm import repo_store
from .llm import api_specs
from .llm import api_review
from .llm import openapi_fields
from .llm import stats as llm_stats
from .llm import shot_templates
from .llm import watch_store
from .llm import watch_run
from .llm.documents import parse_docx, parse_file, parse_txt, parse_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHECK_TIMEOUT = 300
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
CHUNK_LINES = 500
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RULES_FILE = DATA_DIR / "rules.json"
PREFS_FILE = DATA_DIR / "user_prefs.json"
RULE_SEVERITIES = {"error", "warning", "suggestion"}
SESSION_COOKIE = auth.SESSION_COOKIE
COOKIE_SECURE = auth.COOKIE_SECURE

_rules_lock = threading.Lock()
_prefs_lock = threading.Lock()
_check_sem = asyncio.Semaphore(3)

LOGIN_ATTEMPTS: dict[str, list[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW = 300

_cors_raw = os.getenv("PROOFREADER_CORS_ORIGINS", "")
# Список явных origin'ов. Пустой список означает «только same-origin»: с
# allow_credentials=True нельзя ставить "*", иначе это либо не работает в
# браузере, либо (после «починки») открывает кросс-доменный доступ к сессии.
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")

DOCS_ENABLED = os.getenv("PROOFREADER_DOCS", "false").lower() in ("true", "1", "yes")
_docs_kwargs = (
    {"docs_url": "/api/docs", "redoc_url": "/api/redoc", "openapi_url": "/api/openapi.json",
     "swagger_ui_oauth2_redirect_url": "/api/docs/oauth2-redirect"}
    if DOCS_ENABLED
    else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)
app = FastAPI(
    title="Peter View API",
    version="0.1.0",
    description="REST API сервиса вычитки Peter View.",
    **_docs_kwargs,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    """Защита от CSRF: для изменяющих запросов Origin обязан совпадать с хостом.

    Cookie-сессия + SameSite=lax уже отсекают кросс-сайтовые POST, это защита в
    глубину. Если Origin/Referer отсутствуют (не браузер) — пропускаем."""
    if request.method not in _SAFE_METHODS:
        from urllib.parse import urlparse

        # Сравниваем только имена хостов: nginx прокидывает Host без порта
        # ($host), а браузер шлёт Origin с портом — иначе ложные срабатывания.
        host = request.headers.get("host", "").split(":")[0]
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            source_host = urlparse(source).hostname or ""
            if source_host != host and source.rstrip("/") not in CORS_ORIGINS:
                return Response(
                    status_code=403,
                    content=json.dumps({"detail": "Перекрёстный запрос отклонён"}),
                    media_type="application/json",
                )
    return await call_next(request)


@app.middleware("http")
async def feature_gate(request: Request, call_next):
    path = request.url.path
    for prefix, name in (
        ("/api/watch", "watch"),
        ("/api/repo", "documents"),
        ("/api/api-spec", "api"),
        ("/api/screenshot-templates", "screenshots"),
    ):
        if path.startswith(prefix) and not features.enabled(name):
            return Response(
                status_code=404,
                content=json.dumps({"detail": "Раздел недоступен"}),
                media_type="application/json",
            )
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/config")
async def public_config():
    return {
        "version": "0.1.0",
        "features": features.snapshot(),
        "oidc": oidc_login.configured(),
        "docs": DOCS_ENABLED,
    }


@app.get("/api")
async def api_root():
    payload = {"name": "Peter View API", "version": "0.1.0"}
    if DOCS_ENABLED:
        payload.update({"docs": "/api/docs", "redoc": "/api/redoc", "openapi": "/api/openapi.json"})
    return payload


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str
    password: str | None = None
    role: str = "editor"


class UserPatch(BaseModel):
    role: str | None = None


def _session_payload(username: str) -> dict[str, Any]:
    return {
        "username": username,
        "role": auth.role_of(username),
        "source": auth.read_users().get(username, {}).get("source") or "local",
        "jira_base_url": JIRA_BASE_URL,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(SESSION_COOKIE, token, **auth.session_cookie_kwargs())


auth.seed_default_admin()
styleguide_store.seed_default()


def _read_prefs() -> dict[str, dict]:
    with _prefs_lock:
        if not PREFS_FILE.exists():
            return {}
        try:
            data = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def _write_prefs(prefs: dict[str, dict]) -> None:
    with _prefs_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PREFS_FILE.write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_user_styleguide_id(user: str) -> str:
    """id выбранного пользователем гайда; если его нет — встроенный «Базовый»."""
    prefs = _read_prefs()
    chosen = (prefs.get(user) or {}).get("styleguide_id")
    if chosen and styleguide_store.get_guide(chosen) is not None:
        return chosen
    return styleguide_store.DEFAULT_ID


def _set_user_styleguide_id(user: str, styleguide_id: str) -> None:
    prefs = _read_prefs()
    prefs.setdefault(user, {})["styleguide_id"] = styleguide_id
    _write_prefs(prefs)


def _client_ip(request: Request) -> str:
    xr = request.headers.get("x-real-ip")
    if xr:
        return xr.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(key: str) -> bool:
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(key, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW]
    LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) < MAX_LOGIN_ATTEMPTS


def _record_failed_login(key: str) -> None:
    LOGIN_ATTEMPTS.setdefault(key, []).append(time.time())


@app.post("/api/auth/login")
async def login(body: LoginRequest, request: Request):
    username = body.username.strip()
    ip = _client_ip(request)
    pair_key = f"{ip}:{username}"
    ip_key = f"ip:{ip}"

    if not _check_rate_limit(pair_key) or not _check_rate_limit(ip_key):
        raise HTTPException(429, "Слишком много попыток. Подожди 5 минут.")

    users = auth.read_users()
    rec = users.get(username)
    hashed = (rec or {}).get("password") or ""
    if rec is None or rec.get("source") == "oidc" or not auth.check_password(body.password, hashed):
        _record_failed_login(pair_key)
        _record_failed_login(ip_key)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    LOGIN_ATTEMPTS.pop(pair_key, None)
    token = auth.create_session(username)
    audit.append("login", username, source="local")
    response = Response(
        content=json.dumps(_session_payload(username), ensure_ascii=False),
        media_type="application/json",
    )
    _set_session_cookie(response, token)
    return response


@app.get("/api/auth/oidc/start")
async def oidc_start():
    if not oidc_login.configured():
        raise HTTPException(404, "OIDC не настроен")
    return RedirectResponse(await oidc_login.start_url(), status_code=302)


@app.get("/api/auth/oidc/callback")
async def oidc_callback(code: str = "", state: str = ""):
    if not oidc_login.configured():
        raise HTTPException(404, "OIDC не настроен")
    if not code or not state:
        raise HTTPException(400, "Нет кода авторизации")
    info = await oidc_login.exchange(code, state)
    users = auth.read_users()
    username = info["username"]
    existing = next(
        (name for name, rec in users.items() if rec.get("oidc_sub") == info["sub"]),
        username if username in users else None,
    )
    if existing:
        username = existing
        rec = users[username]
        rec["source"] = "oidc"
        rec["oidc_sub"] = info["sub"]
        rec["password"] = ""
        if rec.get("role") != "admin":
            rec["role"] = info["role"]
    else:
        users[username] = {
            "password": "",
            "role": info["role"],
            "source": "oidc",
            "oidc_sub": info["sub"],
        }
    auth.write_users(users)
    token = auth.create_session(username)
    audit.append("login", username, source="oidc")
    response = RedirectResponse("/#/check", status_code=302)
    _set_session_cookie(response, token)
    return response


@app.get("/api/auth/me")
async def me(request: Request):
    username = auth.current_user(request)
    if username is None:
        raise HTTPException(status_code=401, detail="Требуется вход")
    return _session_payload(username)


@app.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth.SESSIONS.pop(token, None)
    response = Response(content=json.dumps({"ok": True}), media_type="application/json")
    response.delete_cookie(SESSION_COOKIE, samesite="lax", httponly=True, secure=COOKIE_SECURE)
    return response


@app.post("/api/auth/change-password")
async def change_password(body: ChangePasswordRequest, request: Request, user: str = Depends(require_user)):
    rate_key = f"pwchange:{_client_ip(request)}:{user}"
    if not _check_rate_limit(rate_key):
        raise HTTPException(429, "Слишком много попыток. Подожди 5 минут.")

    if len(body.new_password) < auth.MIN_PASSWORD:
        raise HTTPException(400, f"Пароль должен содержать минимум {auth.MIN_PASSWORD} символов")

    users = auth.read_users()
    rec = users.get(user)
    if rec is None or rec.get("source") == "oidc":
        raise HTTPException(400, "Пароль меняется у провайдера входа")
    if not auth.check_password(body.current_password, rec.get("password") or ""):
        _record_failed_login(rate_key)
        raise HTTPException(403, "Текущий пароль неверный")

    LOGIN_ATTEMPTS.pop(rate_key, None)
    rec["password"] = auth.hash_password(body.new_password)
    auth.write_users(users)
    auth.drop_sessions(user, keep=request.cookies.get(SESSION_COOKIE))
    audit.append("password_change", user)
    return {"ok": True}


@app.get("/api/users")
async def list_users(_user: str = Depends(require_admin)):
    users = auth.read_users()
    return {
        "users": [
            {"username": name, "role": rec.get("role"), "source": rec.get("source") or "local"}
            for name, rec in sorted(users.items())
        ]
    }


@app.post("/api/users")
async def create_user(body: UserCreate, actor: str = Depends(require_admin)):
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Укажи логин")
    role = body.role if body.role in auth.ROLES else "editor"
    users = auth.read_users()
    if username in users:
        raise HTTPException(409, "Такой логин уже есть")
    password = (body.password or "").strip() or secrets.token_urlsafe(9)
    if len(password) < auth.MIN_PASSWORD:
        raise HTTPException(400, f"Пароль должен содержать минимум {auth.MIN_PASSWORD} символов")
    users[username] = {"password": auth.hash_password(password), "role": role, "source": "local"}
    auth.write_users(users)
    audit.append("user_create", actor, target=username, role=role)
    return {"username": username, "password": password, "role": role}


@app.patch("/api/users/{username}")
async def patch_user(username: str, body: UserPatch, actor: str = Depends(require_admin)):
    users = auth.read_users()
    rec = users.get(username)
    if rec is None:
        raise HTTPException(404, "Пользователь не найден")
    if body.role:
        if body.role not in auth.ROLES:
            raise HTTPException(400, "Неизвестная роль")
        if rec.get("role") == "admin" and body.role != "admin" and auth.admin_count(users) <= 1:
            raise HTTPException(400, "Нельзя снять последнего администратора")
        rec["role"] = body.role
        auth.write_users(users)
        audit.append("role_change", actor, target=username, role=body.role)
    return {"username": username, "role": rec["role"], "source": rec.get("source") or "local"}


@app.delete("/api/users/{username}")
async def delete_user(username: str, actor: str = Depends(require_admin)):
    users = auth.read_users()
    rec = users.get(username)
    if rec is None:
        raise HTTPException(404, "Пользователь не найден")
    if username == actor:
        raise HTTPException(400, "Нельзя удалить себя")
    if rec.get("role") == "admin" and auth.admin_count(users) <= 1:
        raise HTTPException(400, "Нельзя удалить последнего администратора")
    del users[username]
    auth.write_users(users)
    auth.drop_sessions(username)
    audit.append("user_delete", actor, target=username)
    return {"ok": True}


def _parse_user_rules(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _read_rules() -> list[dict[str, str]]:
    with _rules_lock:
        if not RULES_FILE.exists():
            return []
        try:
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []


def _write_rules(rules: list[dict[str, str]]) -> None:
    with _rules_lock:
        RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
        RULES_FILE.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _normalize_rule(rule: dict[str, Any], rule_id: str | None = None) -> dict[str, str]:
    pattern = str(rule.get("pattern", "")).strip()
    message = str(rule.get("message", "")).strip()
    severity = str(rule.get("severity", "warning")).strip()

    if not pattern:
        raise HTTPException(400, "Укажи текст или регулярное выражение")
    if severity not in RULE_SEVERITIES:
        raise HTTPException(400, "Неверный тип правила")
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise HTTPException(400, f"Неверное регулярное выражение: {e}")

    return {
        "id": rule_id or str(uuid.uuid4()),
        "pattern": pattern,
        "message": message or f'Найдено: "{pattern}"',
        "severity": severity,
    }


def _rules_for_check(raw_user_rules: str = "") -> list[dict[str, str]]:
    rules = _read_rules()
    for rule in _parse_user_rules(raw_user_rules):
        try:
            rules.append(_normalize_rule(rule))
        except HTTPException:
            continue
    return rules


def _read_builtin_rules() -> list[dict[str, Any]]:
    return get_registry(include_spelling=True)


class RuleRequest(BaseModel):
    pattern: str
    message: str = ""
    severity: str = "warning"


@app.get("/api/rules")
async def list_rules(_user: str = Depends(require_user)):
    return {"rules": _read_rules()}


@app.get("/api/rules/builtin")
async def list_builtin_rules(_user: str = Depends(require_user)):
    return {"rules": _read_builtin_rules()}


@app.post("/api/rules")
async def create_rule(body: RuleRequest, _user: str = Depends(require_admin)):
    rules = _read_rules()
    rule = _normalize_rule(body.dict())
    rules.append(rule)
    _write_rules(rules)
    return rule


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: str, _user: str = Depends(require_admin)):
    rules = _read_rules()
    kept = [rule for rule in rules if rule.get("id") != rule_id]
    if len(kept) == len(rules):
        raise HTTPException(404, "Правило не найдено")
    _write_rules(kept)
    return {"ok": True}


async def _check_text_chunked(text: str, user_rules=None, include_spelling=True) -> list[dict]:
    """Разбивает длинный текст на чанки, проверяет каждый, склеивает результат."""
    lines = text.split("\n")
    if len(lines) <= CHUNK_LINES:
        async with _check_sem:
            return await check_text(text, user_rules=user_rules, include_spelling=include_spelling)

    all_issues: list[dict] = []
    for start in range(0, len(lines), CHUNK_LINES):
        chunk = "\n".join(lines[start:start + CHUNK_LINES])
        async with _check_sem:
            issues = await check_text(chunk, user_rules=user_rules, include_spelling=include_spelling)
        for issue in issues:
            issue["line"] = issue.get("line", 0) + start
        all_issues.extend(issues)
    return all_issues


@app.post("/api/check")
async def check_file(
    file: UploadFile = File(...),
    user_rules: str = Form(""),
    _user: str = Depends(require_user),
):
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")

    try:
        text = await extract_from_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not text.strip():
        raise HTTPException(400, "Не удалось извлечь текст из файла")

    rules = _rules_for_check(user_rules)
    issues = await _check_text_chunked(text, user_rules=rules)
    for issue in issues:
        issue["page_url"] = ""
    return {
        "source": file.filename,
        "text_length": len(text),
        "pages_checked": 1,
        "issues": issues,
        "summary": _summary(issues),
    }


@app.post("/api/check-url")
async def check_url_stream(
    url: str = Form(...),
    user_rules: str = Form(""),
    _user: str = Depends(require_user),
):
    """Обход сайта + проверка каждой страницы, результат через SSE."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL должен начинаться с http:// или https://")

    rules = _rules_for_check(user_rules)

    async def event_generator():
        all_issues: list[dict] = []
        pages_checked = 0

        async for page in crawl_site(url):
            pages_checked += 1
            logger.info("Page %d crawled: %s (%d chars)", pages_checked, page.url, len(page.text))
            yield {
                "event": "progress",
                "data": json.dumps({
                    "pages_checked": pages_checked,
                    "current_url": page.url,
                }, ensure_ascii=False),
            }

            try:
                logger.info("Checking page %d: %s", pages_checked, page.url)
                async with _check_sem:
                    page_issues = await asyncio.wait_for(
                        check_text(page.text, user_rules=rules),
                        timeout=CHECK_TIMEOUT,
                    )
                logger.info("Page %d checked: %d issues", pages_checked, len(page_issues))
                for issue in page_issues:
                    issue["page_url"] = page.url
                all_issues.extend(page_issues)
            except asyncio.TimeoutError:
                logger.warning("check_text timeout for %s", page.url)

        result = {
            "source": url,
            "pages_checked": pages_checked,
            "issues": all_issues,
            "summary": _summary(all_issues),
        }
        if pages_checked == 0:
            yield {
                "event": "error",
                "data": json.dumps({
                    "message": "Не удалось загрузить ни одной страницы. Проверь URL и доступность сайта с сервера.",
                }, ensure_ascii=False),
            }
            return

        yield {
            "event": "done",
            "data": json.dumps(result, ensure_ascii=False),
        }

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/check-text")
async def check_raw_text(
    text: str = Form(...),
    user_rules: str = Form(""),
    _user: str = Depends(require_user),
):
    if not text.strip():
        raise HTTPException(400, "Текст пустой")
    if len(text) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Текст слишком большой")

    rules = _rules_for_check(user_rules)
    issues = await _check_text_chunked(text, user_rules=rules)
    for issue in issues:
        issue["page_url"] = ""
    return {
        "source": "Текст",
        "text_length": len(text),
        "pages_checked": 1,
        "issues": issues,
        "summary": _summary(issues),
    }


@app.post("/api/report")
async def download_report(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    _user: str = Depends(require_user),
):
    """Проверка файла/текста → xlsx. Для URL используйте /api/report-issues."""
    source_name = ""
    all_issues: list[dict] = []

    if file and file.filename:
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Файл слишком большой")
        extracted = await extract_from_file(content, file.filename)
        source_name = file.filename
        all_issues = await _check_text_chunked(extracted, user_rules=_read_rules())
        for issue in all_issues:
            issue["page_url"] = ""

    elif text:
        source_name = "Текст"
        all_issues = await _check_text_chunked(text, user_rules=_read_rules())
        for issue in all_issues:
            issue["page_url"] = ""

    else:
        raise HTTPException(400, "Укажи файл или текст")

    xlsx_bytes = generate_excel_report(all_issues, source_name)

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="report.xlsx"'},
    )


class ReportRequest(BaseModel):
    issues: list[dict[str, Any]]
    source: str = ""


@app.post("/api/report-issues")
async def report_from_issues(body: ReportRequest, _user: str = Depends(require_user)):
    """xlsx из уже готовых issues (без повторной проверки)."""
    xlsx_bytes = generate_excel_report(body.issues, body.source)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="report.xlsx"'},
    )


@app.post("/api/jobs")
async def create_job(
    file: UploadFile | None = File(None),
    url: str = Form(""),
    text: str = Form(""),
    styleguide_id: str = Form(""),
    check_language: bool = Form(True),
    check_styleguide: bool = Form(True),
    check_consistency: bool = Form(True),
    prompt: str = Form(""),
    user: str = Depends(require_user),
):
    """Ставит документ в очередь LLM-вычитки и возвращает job_id."""
    guide_id = styleguide_id.strip() or _get_user_styleguide_id(user)
    guide = styleguide_store.get_guide(guide_id)
    if guide is None:
        guide = styleguide_store.get_guide(styleguide_store.DEFAULT_ID)
    if guide is None:
        raise HTTPException(400, "Style Guide не найден")
    if not any((check_language, check_styleguide, check_consistency)):
        raise HTTPException(400, "Выбери хотя бы один тип проверки")
    prompt = prompt.strip()
    if len(prompt) > 4000:
        raise HTTPException(400, "Дополнительная инструкция слишком длинная")
    if prompt:
        guide = copy.deepcopy(guide)
        guide.extra_instruction = prompt

    if file and file.filename:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(400, "Файл пустой")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")
        try:
            document = parse_file(content, file.filename)
        except ValueError as e:
            raise HTTPException(400, str(e))
    elif text.strip():
        if len(text) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "Текст слишком большой")
        document = parse_txt(text, source="Текст")
    elif url.strip():
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "URL должен начинаться с http:// или https://")
        try:
            document = await parse_url(url.strip())
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Не удалось загрузить страницу: {e}")
    else:
        raise HTTPException(400, "Укажи файл, текст или URL")

    if not document.blocks:
        raise HTTPException(400, "Не удалось извлечь текст из документа")

    job_id = llm_jobs.submit(
        document,
        guide,
        user=user,
        options={
            "language": check_language,
            "styleguide": check_styleguide,
            "consistency": check_consistency,
        },
    )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str, user: str = Depends(require_user)):
    job = llm_jobs.get_job(job_id)
    if job is None or (job.user and job.user != user):
        raise HTTPException(404, "Задача не найдена")
    return {"job_id": job.id, "status": job.status, "stage": job.stage, "error": job.error}


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request, user: str = Depends(require_user)):
    """SSE-поток живого вывода воркеров: события start/delta/end/finished."""
    job = llm_jobs.get_job(job_id)
    if job is None or (job.user and job.user != user):
        raise HTTPException(404, "Задача не найдена")

    async def gen():
        sent_len: dict[int, int] = {}
        started: set[int] = set()
        ended: set[int] = set()

        def pending() -> bool:
            for pid in list(job.stream_order):
                block = job.stream_blocks.get(pid)
                if block is None:
                    continue
                if pid not in started:
                    return True
                if sent_len.get(pid, 0) < len(block["text"]):
                    return True
                if block["status"] != "running" and pid not in ended:
                    return True
            return job.status in ("done", "error")

        while True:
            if await request.is_disconnected():
                break
            for pid in list(job.stream_order):
                block = job.stream_blocks.get(pid)
                if block is None:
                    continue
                if pid not in started:
                    started.add(pid)
                    yield {"event": "start", "data": json.dumps(
                        {"id": pid, "worker": block["worker"], "scope": block["scope"]},
                        ensure_ascii=False)}
                text = block["text"]
                sl = sent_len.get(pid, 0)
                if sl > len(text):  # текст обрезали с начала — досылать нечего
                    sl = len(text)
                if len(text) > sl:
                    yield {"event": "delta", "data": json.dumps(
                        {"id": pid, "text": text[sl:]}, ensure_ascii=False)}
                    sent_len[pid] = len(text)
                if block["status"] != "running" and pid not in ended:
                    ended.add(pid)
                    yield {"event": "end", "data": json.dumps(
                        {"id": pid, "status": block["status"], "found": block.get("found"),
                         "error": block.get("error")},
                        ensure_ascii=False)}
            if job.status in ("done", "error"):
                yield {"event": "finished", "data": json.dumps(
                    {"status": job.status, "error": job.error}, ensure_ascii=False)}
                break
            wakeup = job.stream_wakeup
            if wakeup is None:
                await asyncio.sleep(0.05)
                continue
            if pending():
                await asyncio.sleep(0)
                continue
            wakeup.clear()
            if pending():
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(wakeup.wait(), timeout=0.4)
            except asyncio.TimeoutError:
                pass

    return EventSourceResponse(
        gen(),
        ping=15,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}/report")
async def job_report(job_id: str, user: str = Depends(require_user)):
    job = llm_jobs.get_job(job_id)
    if job is None or (job.user and job.user != user):
        raise HTTPException(404, "Задача не найдена")
    if job.status == "error":
        raise HTTPException(500, job.error or "Ошибка вычитки")
    if job.status != "done" or job.report is None:
        raise HTTPException(409, "Отчёт ещё не готов")
    return job.report


def _summary(issues: list[dict]) -> dict:
    return {
        "total": len(issues),
        "errors": sum(1 for i in issues if i.get("severity") == "error"),
        "warnings": sum(1 for i in issues if i.get("severity") == "warning"),
        "suggestions": sum(1 for i in issues if i.get("severity") == "suggestion"),
    }


# --- Style Guide ------------------------------------------------------------

class StyleGuideSaveRequest(BaseModel):
    name: str
    rules: list[dict[str, Any]]
    lexicon: dict[str, Any] | None = None


class StyleGuideUpdateRequest(BaseModel):
    name: str | None = None
    rules: list[dict[str, Any]] | None = None
    lexicon: dict[str, Any] | None = None


def _guide_meta(guide, selected_id: str) -> dict:
    return {
        "id": guide.id,
        "name": guide.name,
        "rule_count": len(guide.rules),
        "lexicon_count": len(guide.lexicon_forbidden) + len(guide.lexicon_allowed),
        "builtin": guide.builtin,
        "source_filename": guide.source_filename,
        "created_at": guide.created_at,
        "updated_at": guide.updated_at,
        "created_by": guide.created_by,
        "selected": guide.id == selected_id,
    }


@app.get("/api/styleguides")
async def list_styleguides(user: str = Depends(require_user)):
    selected = _get_user_styleguide_id(user)
    guides = styleguide_store.list_guides()
    return {"styleguides": [_guide_meta(g, selected) for g in guides], "selected": selected}


@app.get("/api/styleguides/current")
async def current_styleguide(user: str = Depends(require_user)):
    return {"selected": _get_user_styleguide_id(user)}


@app.get("/api/styleguides/{guide_id}")
async def get_styleguide(guide_id: str, user: str = Depends(require_user)):
    guide = styleguide_store.get_guide(guide_id)
    if guide is None:
        raise HTTPException(404, "Style Guide не найден")
    return {
        **_guide_meta(guide, _get_user_styleguide_id(user)),
        "rules": guide.rules,
        "lexicon": guide.lexicon or {"forbidden": [], "allowed": []},
    }


@app.get("/api/styleguides/{guide_id}/index-status")
async def styleguide_index_status(guide_id: str, user: str = Depends(require_user)):
    """Режим поиска по гайду: hybrid (семантика + слова) или lexical_only (только слова)."""
    guide = styleguide_store.get_guide(guide_id)
    if guide is None:
        raise HTTPException(404, "Style Guide не найден")
    state = await asyncio.to_thread(llm_rag.retrieval_state, guide)
    return {
        "guide_id": guide_id,
        "status": state["index_status"],
        "fallback_tier": state["fallback_tier"],
        "error": state["index_error"],
    }


@app.post("/api/styleguides/extract")
async def extract_styleguide(
    file: UploadFile = File(...),
    user: str = Depends(require_admin),
):
    """Загрузка docx -> фоновое извлечение правил. Возвращает job_id для опроса."""
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {MAX_UPLOAD_BYTES // 1024 // 1024} МБ)")

    ext = Path(file.filename).suffix.lower()
    try:
        if ext == ".docx":
            document = parse_docx(content, source=file.filename)
        else:
            document = parse_file(content, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not document.full_plain().strip():
        raise HTTPException(400, "Не удалось извлечь текст из документа")

    job_id = extract_jobs.submit(document, file.filename, content)
    return {"job_id": job_id}


@app.get("/api/styleguides/extract/{job_id}")
async def extract_styleguide_status(job_id: str, _user: str = Depends(require_admin)):
    job = extract_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Задача не найдена")
    payload = {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "error": job.error,
        "source_filename": job.source_filename,
    }
    if job.status == "done":
        payload["rules"] = job.rules or []
        payload["lexicon"] = job.lexicon or {"forbidden": [], "allowed": []}
        payload["warning"] = job.warning
        payload["diagnostics"] = job.diagnostics or {}
    return payload


@app.post("/api/styleguides")
async def create_styleguide(body: StyleGuideSaveRequest, user: str = Depends(require_admin)):
    try:
        guide = styleguide_store.save_guide(
            body.name, body.rules, created_by=user, lexicon=body.lexicon
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.append("guide_create", user, guide=guide.id)
    return _guide_meta(guide, _get_user_styleguide_id(user))


@app.put("/api/styleguides/{guide_id}")
async def update_styleguide(guide_id: str, body: StyleGuideUpdateRequest, user: str = Depends(require_admin)):
    try:
        guide = styleguide_store.update_guide(
            guide_id, name=body.name, rules=body.rules, lexicon=body.lexicon
        )
    except KeyError:
        raise HTTPException(404, "Style Guide не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.append("guide_update", user, guide=guide_id)
    return {
        **_guide_meta(guide, _get_user_styleguide_id(user)),
        "rules": guide.rules,
        "lexicon": guide.lexicon or {"forbidden": [], "allowed": []},
    }


@app.delete("/api/styleguides/{guide_id}")
async def delete_styleguide(guide_id: str, user: str = Depends(require_admin)):
    try:
        deleted = styleguide_store.delete_guide(guide_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    if not deleted:
        raise HTTPException(404, "Style Guide не найден")

    if _get_user_styleguide_id(user) == guide_id:
        _set_user_styleguide_id(user, styleguide_store.DEFAULT_ID)
    audit.append("guide_delete", user, guide=guide_id)
    return {"ok": True}


@app.post("/api/styleguides/{guide_id}/select")
async def select_styleguide(guide_id: str, user: str = Depends(require_user)):
    if styleguide_store.get_guide(guide_id) is None:
        raise HTTPException(404, "Style Guide не найден")
    _set_user_styleguide_id(user, guide_id)
    return {"ok": True, "selected": guide_id}


# --- Настройки проверки (глобальные, только для админов) --------------------

class SettingsUpdate(BaseModel):
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float | None = None
    llm_concurrency: int | None = None
    llm_timeout: float | None = None
    llm_json_mode: bool | None = None
    llm_reasoning_effort: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None


class ShotTemplateCreate(BaseModel):
    name: str
    width: int


@app.get("/api/screenshot-templates")
async def list_screenshot_templates(_user: str = Depends(require_user)):
    return {"templates": shot_templates.list_templates()}


@app.post("/api/screenshot-templates")
async def add_screenshot_template(body: ShotTemplateCreate, _user: str = Depends(require_user)):
    try:
        return shot_templates.add_template(body.name, body.width)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/screenshot-templates/{template_id}")
async def delete_screenshot_template(template_id: str, _user: str = Depends(require_user)):
    try:
        shot_templates.delete_template(template_id)
    except KeyError:
        raise HTTPException(404, "Шаблон не найден")
    return {"ok": True}


@app.get("/api/settings")
async def get_settings(_user: str = Depends(require_admin)):
    return llm_settings.get_masked()


@app.put("/api/settings")
async def put_settings(body: SettingsUpdate, user: str = Depends(require_admin)):
    patch = {k: v for k, v in body.dict().items() if v is not None}
    if not patch:
        raise HTTPException(400, "Нет полей для обновления")
    try:
        llm_settings.update(patch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.append("settings_update", user, fields=sorted(patch.keys()))
    return llm_settings.get_masked()


@app.post("/api/settings/test")
async def test_settings(_user: str = Depends(require_admin)):
    """Проверяет доступность LLM и эмбеддингов с текущими настройками."""
    result: dict[str, Any] = {}
    try:
        await asyncio.wait_for(llm_client.healthcheck(), timeout=30)
        result["llm"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["llm"] = {"ok": False, "error": str(e)}
    try:
        await asyncio.wait_for(asyncio.to_thread(llm_rag.healthcheck), timeout=30)
        result["embedding"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["embedding"] = {"ok": False, "error": str(e)}
    return result


# --- История проверок и статистика правил -----------------------------------

@app.get("/api/checks/history")
async def checks_history(user: str = Depends(require_user), limit: int = 10, offset: int = 0):
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    items = llm_stats.recent_history(user, limit=limit, offset=offset)
    total = llm_stats.history_count(user)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/api/checks/history/{history_id}")
async def checks_history_report(history_id: int, user: str = Depends(require_user)):
    report = llm_stats.history_report(user, history_id)
    if report is None:
        raise HTTPException(404, "Отчёт не найден")
    return report


def _rule_titles() -> dict[str, str]:
    """rule_id → человекочитаемый заголовок правила из всех сохранённых гайдов."""
    from .llm import styleguide as _sg
    titles: dict[str, str] = {r["rule_id"]: r["title"] for r in _sg.BASE_RULES}
    for guide in styleguide_store.list_guides():
        for rule in guide.rules:
            rid = str(rule.get("rule_id", "")).strip()
            title = str(rule.get("title", "")).strip()
            if rid and title:
                titles.setdefault(rid, title)
        for entry in guide.lexicon_forbidden:
            rid = str(entry.get("rule_id", "")).strip()
            term = str(entry.get("term", "")).strip()
            if rid and term:
                titles.setdefault(rid, f"Запрещено: «{term}»")
    return titles


@app.get("/api/checks/top-rules")
async def checks_top_rules(_user: str = Depends(require_user)):
    data = llm_stats.top_rules_by_user()
    titles = _rule_titles()
    for user in data.get("users", []):
        for rule in user.get("rules", []):
            rule["title"] = titles.get(rule["rule_id"], "")
    return data


# --- Состояние системы ------------------------------------------------------

@app.get("/api/checks/insights")
async def checks_insights(_user: str = Depends(require_user)):
    data = llm_stats.top_rules_by_user()
    titles = _rule_titles()
    for user in data.get("users", []):
        for rule in user.get("rules", []):
            rule["title"] = titles.get(rule["rule_id"], "")
    return {**data, "tokens": llm_stats.token_totals()}


@app.get("/api/health/full")
async def health_full(_user: str = Depends(require_admin)):
    result: dict[str, Any] = {}
    try:
        await asyncio.wait_for(llm_client.healthcheck(), timeout=20)
        result["llm"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["llm"] = {"ok": False, "error": str(e)}
    try:
        await asyncio.wait_for(asyncio.to_thread(llm_rag.healthcheck), timeout=20)
        result["embedding"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        result["embedding"] = {"ok": False, "error": str(e)}

    import shutil
    try:
        du = shutil.disk_usage(str(DATA_DIR))
        result["disk"] = {"total": du.total, "used": du.used, "free": du.free}
    except OSError as e:
        result["disk"] = {"error": str(e)}

    result["tokens"] = llm_stats.token_totals()
    result["backup"] = backups.last_snapshot()
    result["repo"] = repo_store.usage()
    result["audit"] = audit.recent(80)
    return result


# --- Репозиторий документов на вычитку --------------------------------------

class FolderCreate(BaseModel):
    name: str
    parent_id: str | None = None


@app.on_event("startup")
async def _start_repo_auto_archive():
    if not features.enabled("documents"):
        return

    async def loop():
        while True:
            try:
                await asyncio.to_thread(repo_store.auto_archive_stale)
            except Exception as e:  # noqa: BLE001
                logger.warning("Авто-архив не выполнен: %s", e)
            await asyncio.sleep(6 * 3600)

    asyncio.create_task(loop())


@app.on_event("startup")
async def _start_daily_backup():
    """Раз в сутки делает снимок data/ (если за сегодня ещё не было)."""
    async def loop():
        while True:
            try:
                if await asyncio.to_thread(backups.needs_snapshot_today):
                    await asyncio.to_thread(backups.make_snapshot)
            except Exception as e:  # noqa: BLE001
                logger.warning("Бэкап не выполнен: %s", e)
            await asyncio.sleep(6 * 3600)

    asyncio.create_task(loop())


_watch_running: set[str] = set()


@app.on_event("startup")
async def _start_watch_daily():
    if not features.enabled("watch"):
        return

    async def loop():
        await asyncio.sleep(20)
        while True:
            try:
                await watch_run.run_daily_if_due()
            except Exception as e:  # noqa: BLE001
                logger.warning("Наблюдение не выполнено: %s", e)
            await asyncio.sleep(30 * 60)

    asyncio.create_task(loop())


class WatchGroupCreate(BaseModel):
    name: str
    auth_kind: str = "none"
    login_url: str = ""
    username: str = ""
    password: str = ""
    username_field: str = "username"
    password_field: str = "password"


class WatchGroupPatch(BaseModel):
    name: str | None = None
    auth_kind: str | None = None
    login_url: str | None = None
    username: str | None = None
    password: str | None = None
    username_field: str | None = None
    password_field: str | None = None


class WatchPageCreate(BaseModel):
    url: str
    title: str = ""


class WatchPagePatch(BaseModel):
    url: str | None = None
    title: str | None = None
    enabled: bool | None = None


def _watch_group_out(group: dict) -> dict:
    return {**group, "running": group["id"] in _watch_running}


@app.get("/api/watch/groups")
async def watch_list_groups(_user: str = Depends(require_user)):
    return {"groups": [_watch_group_out(item) for item in watch_store.list_groups()]}


@app.post("/api/watch/groups")
async def watch_create_group(body: WatchGroupCreate, user: str = Depends(require_user)):
    try:
        group = watch_store.create_group(
            body.name,
            auth_kind=body.auth_kind,
            login_url=body.login_url,
            username=body.username,
            password=body.password,
            username_field=body.username_field,
            password_field=body.password_field,
            created_by=user,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _watch_group_out(group)


@app.get("/api/watch/groups/{group_id}")
async def watch_get_group(group_id: str, _user: str = Depends(require_user)):
    group = watch_store.get_group(group_id)
    if group is None:
        raise HTTPException(404, "Группа не найдена")
    return {
        **_watch_group_out(group),
        "pages": watch_store.list_pages(group_id),
    }


@app.patch("/api/watch/groups/{group_id}")
async def watch_patch_group(group_id: str, body: WatchGroupPatch, _user: str = Depends(require_user)):
    fields = body.model_dump(exclude_unset=True)
    try:
        group = watch_store.update_group(group_id, **fields)
    except KeyError:
        raise HTTPException(404, "Группа не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _watch_group_out(group)


@app.delete("/api/watch/groups/{group_id}")
async def watch_delete_group(group_id: str, _user: str = Depends(require_user)):
    if watch_store.get_group(group_id) is None:
        raise HTTPException(404, "Группа не найдена")
    watch_store.delete_group(group_id)
    return {"ok": True}


@app.post("/api/watch/groups/{group_id}/pages")
async def watch_add_page(group_id: str, body: WatchPageCreate, _user: str = Depends(require_user)):
    try:
        page = watch_store.add_page(group_id, body.url, body.title)
    except KeyError:
        raise HTTPException(404, "Группа не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return page


@app.patch("/api/watch/pages/{page_id}")
async def watch_patch_page(page_id: str, body: WatchPagePatch, _user: str = Depends(require_user)):
    fields = body.model_dump(exclude_unset=True)
    try:
        page = watch_store.update_page(page_id, **fields)
    except KeyError:
        raise HTTPException(404, "Адрес не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return page


@app.delete("/api/watch/pages/{page_id}")
async def watch_delete_page(page_id: str, _user: str = Depends(require_user)):
    if watch_store.get_page(page_id) is None:
        raise HTTPException(404, "Адрес не найден")
    watch_store.delete_page(page_id)
    return {"ok": True}


@app.post("/api/watch/groups/{group_id}/run")
async def watch_run_group(group_id: str, _user: str = Depends(require_user)):
    if watch_store.get_group(group_id) is None:
        raise HTTPException(404, "Группа не найдена")
    if group_id in _watch_running:
        return {"status": "running"}
    _watch_running.add(group_id)

    async def _go():
        try:
            await watch_run.check_group(group_id)
        except Exception:  # noqa: BLE001
            logger.exception("Проверка группы наблюдения %s не удалась", group_id)
        finally:
            _watch_running.discard(group_id)

    asyncio.create_task(_go())
    return {"status": "started"}


@app.post("/api/watch/pages/{page_id}/run")
async def watch_run_page(page_id: str, _user: str = Depends(require_user)):
    page = watch_store.get_page(page_id)
    if page is None:
        raise HTTPException(404, "Адрес не найден")
    group_id = page["group_id"]
    key = f"page:{page_id}"
    if key in _watch_running or group_id in _watch_running:
        return {"status": "running"}
    _watch_running.add(key)

    async def _go():
        try:
            await watch_run.check_page(page_id)
        except Exception:  # noqa: BLE001
            logger.exception("Проверка адреса наблюдения %s не удалась", page_id)
        finally:
            _watch_running.discard(key)

    asyncio.create_task(_go())
    return {"status": "started"}


@app.get("/api/watch/pages/{page_id}/diff")
async def watch_page_diff(page_id: str, _user: str = Depends(require_user)):
    try:
        return watch_run.page_diff(page_id)
    except KeyError:
        raise HTTPException(404, "Адрес не найден")


@app.get("/api/watch/pages/{page_id}/history")
async def watch_page_history(page_id: str, _user: str = Depends(require_user)):
    if watch_store.get_page(page_id) is None:
        raise HTTPException(404, "Адрес не найден")
    return {"items": watch_store.list_snapshots(page_id)}


def _doc_summary(doc: dict, views: dict[str, float] | None = None) -> dict:
    versions = doc.get("versions", [])
    latest = versions[-1] if versions else {}
    last_activity = doc.get("last_activity_at", 0)
    seen_at = (views or {}).get(doc["id"], 0)
    return {
        "id": doc["id"],
        "name": doc["name"],
        "folder_id": doc.get("folder_id"),
        "archived": bool(doc.get("archived")),
        "version_count": len(versions),
        "created_by": doc.get("created_by", ""),
        "created_at": doc.get("created_at", 0),
        "last_activity_at": last_activity,
        "is_new": views is not None and last_activity > seen_at,
        "latest": {
            "number": latest.get("number"),
            "uploaded_by": latest.get("uploaded_by", ""),
            "note": latest.get("note", ""),
            "jira": latest.get("jira", ""),
            "created_at": latest.get("created_at", 0),
            "filename": latest.get("filename", ""),
        } if latest else None,
    }


def _folder_summary(folder: dict) -> dict:
    sub = len(repo_store.list_child_folders(folder["id"]))
    docs = len(repo_store.list_documents(folder["id"]))
    return {
        "id": folder["id"],
        "name": folder["name"],
        "parent_id": folder.get("parent_id"),
        "created_by": folder.get("created_by", ""),
        "created_at": folder.get("created_at", 0),
        "item_count": sub + docs,
    }


@app.get("/api/repo/folders")
async def repo_list_folder(parent: str = "", user: str = Depends(require_user)):
    folder_id = parent.strip() or None
    if folder_id in ("root", "null"):
        folder_id = None
    if folder_id and not repo_store.breadcrumbs(folder_id):
        raise HTTPException(404, "Папка не найдена")
    views = llm_stats.last_views(user)
    return {
        "folder_id": folder_id,
        "breadcrumbs": repo_store.breadcrumbs(folder_id),
        "folders": [_folder_summary(f) for f in repo_store.list_child_folders(folder_id)],
        "documents": [_doc_summary(d, views) for d in repo_store.list_documents(folder_id)],
    }


@app.get("/api/repo/archived")
async def repo_archived(user: str = Depends(require_user)):
    views = llm_stats.last_views(user)
    return {"documents": [_doc_summary(d, views) for d in repo_store.list_archived()]}


@app.get("/api/repo/search")
async def repo_search(q: str = "", user: str = Depends(require_user)):
    views = llm_stats.last_views(user)
    return {"documents": [_doc_summary(d, views) for d in repo_store.search(q)]}


@app.get("/api/repo/tree")
async def repo_tree(_user: str = Depends(require_user)):
    """Плоский список всех папок для выбора при перемещении."""
    return {"folders": repo_store.all_folders()}


@app.get("/api/repo/usage")
async def repo_usage(_user: str = Depends(require_user)):
    return repo_store.usage()


@app.post("/api/repo/folders")
async def repo_create_folder(body: FolderCreate, user: str = Depends(require_user)):
    try:
        folder = repo_store.create_folder(body.name, body.parent_id, created_by=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _folder_summary(folder)


@app.delete("/api/repo/folders/{folder_id}")
async def repo_delete_folder(folder_id: str, _user: str = Depends(require_user)):
    try:
        repo_store.delete_folder(folder_id)
    except KeyError:
        raise HTTPException(404, "Папка не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Файл пустой")
    if len(content) > repo_store.MAX_FILE_BYTES:
        raise HTTPException(400, f"Файл слишком большой (макс. {repo_store.MAX_FILE_BYTES // 1024 // 1024} МБ)")
    return content


@app.post("/api/repo/documents")
async def repo_create_document(
    file: UploadFile = File(...),
    folder_id: str = Form(""),
    name: str = Form(""),
    note: str = Form(""),
    jira: str = Form(""),
    user: str = Depends(require_user),
):
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")
    content = await _read_upload(file)
    try:
        doc = repo_store.create_document(
            folder_id.strip() or None, name, file.filename, content,
            uploaded_by=user, note=note, jira=jira,
        )
    except repo_store.QuotaError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _doc_summary(doc)


class RepoDocPatch(BaseModel):
    name: str | None = None
    folder_id: str | None = None
    move: bool = False  # отличить «перенести в корень» (folder_id=None) от «не трогать»


class RepoFolderPatch(BaseModel):
    name: str | None = None
    parent_id: str | None = None
    move: bool = False


@app.get("/api/repo/documents/{doc_id}")
async def repo_get_document(doc_id: str, user: str = Depends(require_user)):
    doc = repo_store.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, "Документ не найден")
    llm_stats.mark_seen(user, doc_id)
    return doc


@app.patch("/api/repo/documents/{doc_id}")
async def repo_patch_document(doc_id: str, body: RepoDocPatch, user: str = Depends(require_user)):
    try:
        doc = repo_store.get_document(doc_id)
        if doc is None:
            raise KeyError(doc_id)
        if body.name is not None:
            doc = repo_store.rename_document(doc_id, body.name)
        if body.move:
            doc = repo_store.move_document(doc_id, body.folder_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _doc_summary(doc, llm_stats.last_views(user))


@app.patch("/api/repo/folders/{folder_id}")
async def repo_patch_folder(folder_id: str, body: RepoFolderPatch, _user: str = Depends(require_user)):
    try:
        if body.name is not None:
            repo_store.rename_folder(folder_id, body.name)
        if body.move:
            repo_store.move_folder(folder_id, body.parent_id)
    except KeyError:
        raise HTTPException(404, "Папка не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    folder = repo_store.get_folder(folder_id)
    if folder is None:
        raise HTTPException(404, "Папка не найдена")
    return _folder_summary(folder)


@app.post("/api/repo/documents/{doc_id}/versions")
async def repo_add_version(
    doc_id: str,
    file: UploadFile = File(...),
    note: str = Form(""),
    jira: str = Form(""),
    kind: str = Form("upload"),
    user: str = Depends(require_user),
):
    if not file.filename:
        raise HTTPException(400, "Имя файла отсутствует")
    content = await _read_upload(file)
    try:
        doc = repo_store.add_version(
            doc_id, file.filename, content, uploaded_by=user, note=note, jira=jira,
            kind=("review" if kind == "review" else "upload"),
        )
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    except repo_store.QuotaError as e:
        raise HTTPException(400, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _doc_summary(doc)


@app.get("/api/repo/documents/{doc_id}/versions/{number}")
async def repo_download_version(doc_id: str, number: int, _user: str = Depends(require_user)):
    from urllib.parse import quote
    try:
        filename, data = repo_store.version_bytes(doc_id, number)
    except KeyError:
        raise HTTPException(404, "Версия не найдена")
    ascii_name = filename.encode("ascii", "ignore").decode() or f"v{number}"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@app.post("/api/repo/documents/{doc_id}/archive")
async def repo_archive(doc_id: str, _user: str = Depends(require_user)):
    try:
        doc = repo_store.archive_document(doc_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    return _doc_summary(doc)


@app.post("/api/repo/documents/{doc_id}/unarchive")
async def repo_unarchive(doc_id: str, _user: str = Depends(require_user)):
    try:
        doc = repo_store.unarchive_document(doc_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    return _doc_summary(doc)


@app.delete("/api/repo/documents/{doc_id}")
async def repo_delete_document(doc_id: str, _user: str = Depends(require_user)):
    try:
        repo_store.delete_document(doc_id)
    except KeyError:
        raise HTTPException(404, "Документ не найден")
    return {"ok": True}


# --- Вычитка API: связки RU/EN документов OpenAPI -----------------------------

class ApiSpecCreate(BaseModel):
    name: str
    ru_doc_id: str
    en_doc_id: str


class ApiSpecPatch(BaseModel):
    name: str | None = None
    ru_doc_id: str | None = None
    en_doc_id: str | None = None


def _spec_summary(spec: dict) -> dict:
    ru = api_specs.doc_meta(spec["ru_doc_id"])
    en = api_specs.doc_meta(spec["en_doc_id"])
    return {
        "id": spec["id"],
        "name": spec["name"],
        "created_by": spec.get("created_by", ""),
        "created_at": spec.get("created_at", 0),
        "ru": ru,
        "en": en,
        "has_previous": api_specs.has_diff_baseline(spec["ru_doc_id"]),
    }


def _spec_or_404(spec_id: str) -> dict:
    spec = api_specs.get_spec(spec_id)
    if spec is None:
        raise HTTPException(404, "Связка не найдена")
    return spec


def _build_segments(spec: dict, page: int, size: int, q: str = "") -> dict:
    ru_latest, ru_num, _, _ = api_specs.latest_and_previous(spec["ru_doc_id"])
    en_latest, en_num, _, _ = api_specs.latest_and_previous(spec["en_doc_id"])
    ru_fields = openapi_fields.extract_fields(ru_latest)
    en_fields = openapi_fields.extract_fields(en_latest)
    rows = openapi_fields.pair_fields(ru_fields, en_fields)
    q = (q or "").strip()
    if q:
        ql = q.casefold()
        rows = [
            r for r in rows
            if ql in (r.get("context") or "").casefold()
            or ql in (r.get("ru_text") or "").casefold()
            or ql in (r.get("en_text") or "").casefold()
            or ql in (r.get("path_str") or "").casefold()
        ]
    total = len(rows)
    start = page * size
    return {
        "total": total,
        "page": page,
        "size": size,
        "query": q,
        "ru_version": ru_num,
        "en_version": en_num,
        "segments": rows[start:start + size],
    }


def _build_diff(spec: dict) -> dict:
    latest, lnum, prev, pnum = api_specs.diff_versions(spec["ru_doc_id"])
    if prev is None:
        return {"has_previous": False, "from_version": None, "to_version": lnum, "changes": []}
    new_fields = openapi_fields.extract_fields(latest)
    old_fields = openapi_fields.extract_fields(prev)
    changes = openapi_fields.diff_fields(old_fields, new_fields)
    # подтянем текущий EN-текст к изменённым RU-полям для контекста/перевода
    en_latest, _, _, _ = api_specs.latest_and_previous(spec["en_doc_id"])
    en_by_path = {f["path_str"]: f["text"] for f in openapi_fields.extract_fields(en_latest)}
    for c in changes:
        c["en_text"] = en_by_path.get(c["path_str"])
    return {"has_previous": True, "from_version": pnum, "to_version": lnum, "changes": changes}


@app.get("/api/api-specs")
async def api_list_specs(_user: str = Depends(require_user)):
    return {"specs": [_spec_summary(s) for s in api_specs.list_specs()]}


@app.get("/api/api-spec-documents")
async def api_spec_documents(_user: str = Depends(require_user)):
    """Документы репозитория для выбора RU/EN при создании связки."""
    return {"documents": api_specs.documents_for_picker()}


@app.post("/api/api-specs")
async def api_create_spec(body: ApiSpecCreate, user: str = Depends(require_user)):
    try:
        spec = api_specs.create_spec(body.name, body.ru_doc_id, body.en_doc_id, created_by=user)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _spec_summary(spec)


@app.patch("/api/api-specs/{spec_id}")
async def api_patch_spec(spec_id: str, body: ApiSpecPatch, _user: str = Depends(require_user)):
    try:
        spec = api_specs.update_spec(spec_id, body.name, body.ru_doc_id, body.en_doc_id)
    except KeyError:
        raise HTTPException(404, "Связка не найдена")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _spec_summary(spec)


@app.delete("/api/api-specs/{spec_id}")
async def api_delete_spec(spec_id: str, _user: str = Depends(require_user)):
    try:
        api_specs.delete_spec(spec_id)
    except KeyError:
        raise HTTPException(404, "Связка не найдена")
    return {"ok": True}


@app.get("/api/api-specs/{spec_id}/segments")
async def api_spec_segments(spec_id: str, page: int = 0, size: int = 25, q: str = "", _user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)
    page = max(0, page)
    size = max(1, min(size, 250))
    try:
        return await asyncio.to_thread(_build_segments, spec, page, size, q)
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _build_consistency(spec: dict, lang: str) -> dict:
    doc_id = spec["ru_doc_id"] if lang == "ru" else spec["en_doc_id"]
    latest, num, _, _ = api_specs.latest_and_previous(doc_id)
    fields = openapi_fields.extract_fields(latest)
    report = openapi_fields.consistency_report(fields)
    report["lang"] = lang
    report["version"] = num
    return report


@app.get("/api/api-specs/{spec_id}/consistency")
async def api_spec_consistency(spec_id: str, lang: str = "ru", _user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)
    lang = "en" if lang == "en" else "ru"
    try:
        return await asyncio.to_thread(_build_consistency, spec, lang)
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/api-specs/{spec_id}/diff")
async def api_spec_diff(spec_id: str, _user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)
    try:
        return await asyncio.to_thread(_build_diff, spec)
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))


def _diff_changes(spec: dict) -> list[dict]:
    latest, _, prev, _ = api_specs.diff_versions(spec["ru_doc_id"])
    if prev is None:
        return []
    new_fields = openapi_fields.extract_fields(latest)
    old_fields = openapi_fields.extract_fields(prev)
    return openapi_fields.diff_fields(old_fields, new_fields)


@app.post("/api/api-specs/{spec_id}/ai-review")
async def api_spec_ai_review(spec_id: str, user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)

    async def runner(progress):
        progress("Готовлю дифф")
        changes = await asyncio.to_thread(_diff_changes, spec)
        if not changes:
            return {"type": "api-review", "changed": 0, "issues": [],
                    "message": "Изменений для проверки нет"}
        progress(f"Проверка изменений: {len(changes)}")
        issues = await api_review.review_segments(changes)
        return {"type": "api-review", "changed": len(changes), "issues": issues}

    job_id = llm_jobs.submit_task(f"api-review:{spec['name']}", runner, user=user)
    return {"job_id": job_id}


@app.post("/api/api-specs/{spec_id}/translate")
async def api_spec_translate(spec_id: str, user: str = Depends(require_user)):
    spec = _spec_or_404(spec_id)

    async def runner(progress):
        progress("Готовлю дифф")
        changes = await asyncio.to_thread(_diff_changes, spec)
        if not changes:
            return {"type": "api-translate", "changed": 0, "translations": [],
                    "message": "Изменений для перевода нет"}
        progress(f"Перевожу изменения: {len(changes)}")
        mapping = await api_review.translate_segments(changes)
        translations = [
            {
                "path_str": c["path_str"],
                "context": c["context"],
                "ru_text": c["new_text"],
                "en_text": mapping.get(c["path_str"], ""),
            }
            for c in changes
        ]
        return {"type": "api-translate", "changed": len(changes), "translations": translations}

    job_id = llm_jobs.submit_task(f"api-translate:{spec['name']}", runner, user=user)
    return {"job_id": job_id}


class ApiEdits(BaseModel):
    target: str  # "ru" | "en"
    edits: dict[str, str]


@app.post("/api/api-specs/{spec_id}/download")
async def api_spec_download(spec_id: str, body: ApiEdits, _user: str = Depends(require_user)):
    """Применяет правки к последней версии RU/EN и отдаёт исправленный YAML файлом."""
    from urllib.parse import quote
    spec = _spec_or_404(spec_id)
    doc_id = spec["ru_doc_id"] if body.target == "ru" else spec["en_doc_id"]
    meta = api_specs.doc_meta(doc_id)
    try:
        latest, _, _, _ = api_specs.latest_and_previous(doc_id)
        data = await asyncio.to_thread(openapi_fields.apply_edits, latest, body.edits or {})
    except KeyError:
        raise HTTPException(404, "Документ связки не найден")
    except ValueError as e:
        raise HTTPException(400, str(e))
    base = (meta["filename"] if meta and meta.get("filename") else f"{body.target}.yaml")
    name = base.rsplit(".", 1)[0] + "_edited." + (base.rsplit(".", 1)[1] if "." in base else "yaml")
    ascii_name = name.encode("ascii", "ignore").decode() or "edited.yaml"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(content=data, media_type="application/x-yaml",
                    headers={"Content-Disposition": disposition})


_OPENAPI_TAGS = [
    {"name": "Служебное", "description": "Проверка доступности и состояние сервисов."},
    {"name": "Авторизация", "description": "Сессия, текущий пользователь, смена пароля."},
    {"name": "Пользователи", "description": "Учётные записи. Только для администратора."},
    {"name": "Правила", "description": "Пользовательские и встроенные правила вычитки."},
    {"name": "Вычитка", "description": "Синхронная проверка файла, URL или текста."},
    {"name": "Отчёты", "description": "Выгрузка найденных замечаний в Excel."},
    {"name": "Задачи", "description": "Асинхронные проверки, SSE-поток воркеров и отчёт."},
    {"name": "Style Guide", "description": "Правила, лексикон, извлечение из документа."},
    {"name": "Скриншоты", "description": "Шаблоны ширины для редактора скриншотов."},
    {"name": "Настройки", "description": "Ключи и адреса LLM и эмбеддингов."},
    {"name": "История", "description": "Прошлые проверки и статистика правил."},
    {"name": "Наблюдение", "description": "Группы внешних URL, вход на портал и ежедневное сравнение текста."},
    {"name": "Репозиторий", "description": "Папки, документы, версии и архив."},
    {"name": "Спецификации API", "description": "RU/EN OpenAPI-связки, поля, дифф и перевод."},
]

_PATH_TAGS = (
    ("/api/auth", "Авторизация"),
    ("/api/users", "Пользователи"),
    ("/api/rules", "Правила"),
    ("/api/check", "Вычитка"),
    ("/api/report", "Отчёты"),
    ("/api/jobs", "Задачи"),
    ("/api/styleguides", "Style Guide"),
    ("/api/screenshot-templates", "Скриншоты"),
    ("/api/settings", "Настройки"),
    ("/api/checks", "История"),
    ("/api/health", "Служебное"),
    ("/api/watch", "Наблюдение"),
    ("/api/repo", "Репозиторий"),
    ("/api/api-spec", "Спецификации API"),
)


def _tag_for_path(path: str) -> str:
    for prefix, tag in sorted(_PATH_TAGS, key=lambda item: len(item[0]), reverse=True):
        if path.startswith(prefix):
            return tag
    return "Служебное"


def _apply_openapi_tags() -> None:
    for route in app.routes:
        if isinstance(route, APIRoute) and not route.tags:
            route.tags = [_tag_for_path(route.path)]


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    _apply_openapi_tags()
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=_OPENAPI_TAGS,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["CookieAuth"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": SESSION_COOKIE,
        "description": "Cookie сессии после POST /api/auth/login.",
    }
    public = {("/api", "get"), ("/api/health", "get"), ("/api/auth/login", "post"), ("/api/docs", "get"),
              ("/api/redoc", "get"), ("/api/openapi.json", "get")}
    for path, item in schema.get("paths", {}).items():
        for method, operation in item.items():
            if not isinstance(operation, dict):
                continue
            if (path, method.lower()) in public:
                continue
            operation.setdefault("security", [{"CookieAuth": []}])
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

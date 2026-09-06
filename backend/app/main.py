from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import Response
from fastapi.routing import APIRoute

from . import auth, features
from .llm import styleguide_store
from .routers import (
    auth as auth_routes,
    background,
    checks,
    history,
    jobs,
    repo,
    reports,
    rules,
    settings,
    shots,
    specs,
    styleguides,
    system,
    users,
    watch,
)
from .routers.infra import DOCS_ENABLED
from .routers.openapi_meta import _OPENAPI_TAGS, _PATH_TAGS
from .routers.session import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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
    if request.method not in _SAFE_METHODS:
        from urllib.parse import urlparse

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


auth.seed_default_admin()
styleguide_store.seed_default()

app.include_router(system.router)
app.include_router(auth_routes.router)
app.include_router(users.router)
app.include_router(rules.router)
app.include_router(checks.router)
app.include_router(reports.router)
app.include_router(jobs.router)
app.include_router(styleguides.router)
app.include_router(shots.router)
app.include_router(settings.router)
app.include_router(history.router)
app.include_router(watch.router)
app.include_router(repo.router)
app.include_router(specs.router)

app.on_event("startup")(background.start_repo_auto_archive)
app.on_event("startup")(background.start_daily_backup)
app.on_event("startup")(background.start_watch_daily)


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
        "name": auth.SESSION_COOKIE,
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

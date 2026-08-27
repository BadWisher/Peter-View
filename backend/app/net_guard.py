"""Защита от SSRF для всех исходящих HTTP-запросов по пользовательскому URL.

Сервис ходит на внешние сайты (проверка по ссылке, краулер, загрузка URL).
Чтобы из контейнера нельзя было дотянуться до служебных адресов (loopback,
облачные метаданные 169.254.169.254 и т.п.), перед каждым запросом резолвим
хост и проверяем все полученные IP. Редиректы проходят ту же проверку
поштучно, а размер ответа ограничен.

Приватные адреса (10/8, 192.168/16, ...) по умолчанию РАЗРЕШЕНЫ: сервис живёт
в корпоративной локальной сети и проверяет внутреннюю документацию. Их можно
запретить через PROOFREADER_SSRF_ALLOW_PRIVATE=false.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urljoin, urlparse
from typing import Any

import httpx

ALLOW_PRIVATE = os.getenv("PROOFREADER_SSRF_ALLOW_PRIVATE", "true").lower() in ("true", "1", "yes")
MAX_FETCH_BYTES = int(os.getenv("PROOFREADER_MAX_FETCH_BYTES", str(10 * 1024 * 1024)))
MAX_REDIRECTS = int(os.getenv("PROOFREADER_MAX_REDIRECTS", "5"))


class BlockedURLError(ValueError):
    """URL указывает на запрещённый адрес или нарушает лимиты."""


def _ip_blocked(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if (
        addr.is_loopback
        or addr.is_link_local  # 169.254/16 и fe80::/10 — сюда же метаданные облака
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    ):
        return True
    if not ALLOW_PRIVATE and addr.is_private:
        return True
    return False


async def assert_public_url(url: str) -> None:
    """Бросает BlockedURLError, если схема не http(s) или хост резолвится в служебный IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError("URL должен начинаться с http:// или https://")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("В URL нет хоста")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise BlockedURLError(f"Не удалось разрешить хост: {host}")
    for info in infos:
        ip = info[4][0]
        if _ip_blocked(ip):
            raise BlockedURLError(f"Доступ к внутреннему адресу запрещён: {ip}")


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_FETCH_BYTES,
    **kwargs,
) -> httpx.Response:
    """GET с проверкой каждого хопа против SSRF и ограничением размера тела."""
    return await safe_request(
        client, "GET", url, max_redirects=max_redirects, max_bytes=max_bytes, **kwargs,
    )


async def safe_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    auth: httpx.Auth | tuple[str, str] | None = None,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_FETCH_BYTES,
) -> httpx.Response:
    """HTTP-запрос с проверкой каждого хопа против SSRF и лимитом размера тела.

    Редиректы следуем вручную. После POST 301/302/303 дальше идём GET, чтобы
    не повторять тело логина.
    """
    current = url
    current_method = method.upper()
    current_data = data
    for _ in range(max_redirects + 1):
        await assert_public_url(current)
        request_headers = dict(headers or {})
        kw: dict[str, Any] = {
            "follow_redirects": False,
            "headers": request_headers or None,
        }
        if auth is not None:
            kw["auth"] = auth
        if current_method in ("POST", "PUT", "PATCH") and current_data is not None:
            kw["data"] = current_data
        async with client.stream(current_method, current, **kw) as resp:
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise BlockedURLError("Редирект без заголовка Location")
                current = urljoin(current, location)
                if current_method == "POST" and resp.status_code in (301, 302, 303):
                    current_method = "GET"
                    current_data = None
                continue
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > max_bytes:
                    raise BlockedURLError("Ответ слишком большой")
            response_headers = httpx.Headers(resp.headers)
            for h in ("content-encoding", "content-length", "transfer-encoding"):
                if h in response_headers:
                    del response_headers[h]
            return httpx.Response(
                status_code=resp.status_code,
                headers=response_headers,
                content=bytes(buf),
                request=resp.request,
            )
    raise BlockedURLError("Слишком много редиректов")

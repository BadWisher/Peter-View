"""Съём страницы через живой браузер, а не голый HTTP.

Текстовый фетчер не видит интерфейсы, которые дорисовывает JS: SPA-каркасы,
порталы с рендером на клиенте, подгружаемые блоки. Такие страницы раньше
падали в «почти пусто» и наблюдение по ним молча не работало. Здесь страница
открывается в headless Chromium (Playwright), ждёт сеть и возвращает
отрендеренный DOM — дальше его разбирают те же snapshot_text/snapshot_nodes.

Браузер поднимается лениво и один на процесс: держать его ради каждого
портала отдельно дорого, а запускать на каждый чих — медленно. Если
Playwright не установлен или страница не открылась за таймаут — честная
ошибка наружу, а не тихий пропуск.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

RENDER_TIMEOUT = int(os.getenv("PROOFREADER_WATCH_RENDER_TIMEOUT", "25"))
SETTLE_MS = int(os.getenv("PROOFREADER_WATCH_RENDER_SETTLE_MS", "1200"))

_browser = None
_browser_lock = asyncio.Lock()
_playwright = None


def render_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


async def _browser_lazy():
    global _browser, _playwright
    if _browser is not None:
        return _browser
    async with _browser_lock:
        if _browser is not None:
            return _browser
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ValueError(
                "Страница требует JS, а рендера нет: поставь playwright и chromium "
                "(pip install playwright && playwright install chromium)"
            ) from exc
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(args=[
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
        ])
        return _browser


async def render_html(url: str, cookies: list[dict] | None = None) -> str:
    """Открыть страницу в браузере и вернуть HTML после JS."""
    browser = await _browser_lazy()
    page = await browser.new_page(user_agent=(
        "Mozilla/5.0 (compatible; PeterViewWatch/1.0)"
    ))
    try:
        if cookies:
            await page.context.add_cookies(cookies)
        await page.goto(url, timeout=RENDER_TIMEOUT * 1000, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass  # живые счётчики и лонгполлы висят вечно — не ждём их
        await page.wait_for_timeout(SETTLE_MS)
        html = await page.content()
        return html
    finally:
        await page.close()

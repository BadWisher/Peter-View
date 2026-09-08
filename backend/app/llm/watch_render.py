"""Съём страницы через живой браузер, а не голый HTTP.

Текстовый фетчер не видит интерфейсы, которые дорисовывает JS: SPA-каркасы,
порталы с рендером на клиенте, подгружаемые блоки. Такие страницы раньше
падали в «почти пусто» и мониторинг по ним молча не работал. Здесь страница
открывается в headless Chromium (Playwright), ждёт сеть и возвращает
отрендеренный DOM — дальше его разбирают те же snapshot_text/snapshot_nodes.

Браузер поднимается лениво и один на процесс: держать его ради каждого
портала отдельно дорого, а запускать на каждый чих — медленно. Если
Playwright не установлен или страница не открылась за таймаут — честная
ошибка наружу, а не тихий пропуск.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os

logger = logging.getLogger(__name__)

RENDER_TIMEOUT = int(os.getenv("PROOFREADER_WATCH_RENDER_TIMEOUT", "25"))
SETTLE_MS = int(os.getenv("PROOFREADER_WATCH_RENDER_SETTLE_MS", "1200"))

_browser = None
_browser_lock = asyncio.Lock()
_playwright = None
_browser_loop = None


def _chromium_ready() -> bool:
    """Бинарник chromium на месте? Playwright ищет его в
    PLAYWRIGHT_BROWSERS_PATH (в образе это /opt/ms-playwright) или в
    ~/.cache/ms-playwright. Проверяем тот же корень: без файла launch
    гарантированно падает, и раньше это молча превращало снимок в голую
    статику, которая рендерится кашей."""
    base = os.getenv("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser(
        "~/.cache/ms-playwright")
    for d in glob.glob(os.path.join(base, "chromium*")):
        for tail in ("chrome-linux64/chrome", "chrome-linux/chrome",
                     "chrome-linux/headless_shell"):
            if os.path.exists(os.path.join(d, tail)):
                return True
    return False


def render_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return _chromium_ready()


async def _browser_lazy():
    global _browser, _playwright, _browser_loop
    loop = asyncio.get_running_loop()
    # Браузер привязан к тому циклу, где запустили. Новый цикл (тесты гоняют
    # asyncio.run на каждый кейс) — старый экземпляр мёртв, поднимаем заново.
    if _browser is not None and _browser_loop is loop:
        return _browser
    async with _browser_lock:
        if _browser is not None and _browser_loop is loop:
            return _browser
        _browser = _playwright = _browser_loop = None
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
        _browser_loop = loop
        return _browser


async def render_html(url: str, cookies: list[dict] | None = None) -> str:
    """Открыть страницу в браузере и вернуть HTML после JS."""
    browser = await _browser_lazy()
    # Десктопный UA: под «PeterViewWatch» адаптивные сайты отдают мобильную
    # вёрстку, и копия расходится с тем, что видит пользователь.
    page = await browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    )
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


MAX_SHOT_HEIGHT = 12000


async def screenshot_html(html: str, width: int = 1280) -> bytes:
    """Сделать PNG из готовой копии: тот же браузер, что снимает страницы.

    Снимок ровно такой, каким его видит панель: свои стили, свои метки.
    Длиннее MAX_SHOT_HEIGHT не разворачиваем, иначе на простынях вроде
    вики страница съедает всю память.
    """
    browser = await _browser_lazy()
    page = await browser.new_page(viewport={"width": width, "height": 900})
    try:
        await page.set_content(html, timeout=RENDER_TIMEOUT * 1000)
        try:
            await page.wait_for_load_state("networkidle", timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(SETTLE_MS)
        height = await page.evaluate("() => document.documentElement.scrollHeight")
        if height > MAX_SHOT_HEIGHT:
            return await page.screenshot(
                type="png", clip={"x": 0, "y": 0, "width": width, "height": MAX_SHOT_HEIGHT})
        return await page.screenshot(type="png", full_page=True)
    finally:
        await page.close()

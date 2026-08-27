"""BFS-краулер: обходит сайт в ширину, до 200 страниц, 5 параллельных запросов."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import AsyncIterator
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

from .extractors import extract_html
from .net_guard import safe_get

MAX_PAGES = 200
MAX_CONCURRENT = 5
PAGE_TIMEOUT = 20.0
BOT_USER_AGENT = "Proofreader/1.0"

SKIP_EXTENSIONS = frozenset((
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".msi", ".dmg", ".apk",
    ".css", ".js", ".json", ".xml", ".rss", ".atom",
    ".woff", ".woff2", ".ttf", ".eot",
))


@dataclass
class CrawledPage:
    url: str
    text: str


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _same_domain(base_url: str, candidate: str) -> bool:
    base_host = urlparse(base_url).netloc
    cand_host = urlparse(candidate).netloc
    return cand_host == base_host


def _should_skip(url: str) -> bool:
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    for ext in SKIP_EXTENSIONS:
        if path_lower.endswith(ext):
            return True
    if parsed.scheme not in ("http", "https"):
        return True
    return False


def _extract_links(html: str, base_url: str) -> list[str]:
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []
    results = []
    for href in parser.links:
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base_url, href)
        normalized = _normalize_url(absolute)
        if _same_domain(base_url, normalized) and not _should_skip(normalized):
            results.append(normalized)
    return results


async def _load_robots(client: httpx.AsyncClient, base_url: str) -> RobotFileParser | None:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = await safe_get(client, robots_url)
        if resp.status_code == 200:
            rp = RobotFileParser()
            rp.parse(resp.text.splitlines())
            return rp
    except Exception:
        pass
    return None


async def crawl_site(start_url: str) -> AsyncIterator[CrawledPage]:
    """Обход сайта в ширину, yield'ит страницы по мере загрузки."""
    visited: set[str] = set()
    queue: deque[str] = deque()

    start_normalized = _normalize_url(start_url)
    queue.append(start_normalized)
    visited.add(start_normalized)

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    pages_yielded = 0

    async with httpx.AsyncClient(
        timeout=PAGE_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": f"Mozilla/5.0 (compatible; {BOT_USER_AGENT})"},
    ) as client:

        robots = await _load_robots(client, start_url)
        if robots:
            logger.info("robots.txt загружен для %s", urlparse(start_url).netloc)

        async def fetch_page(url: str) -> tuple[str, str, str] | None:
            if robots and not robots.can_fetch(BOT_USER_AGENT, url):
                logger.info("Blocked by robots.txt: %s", url)
                return None
            async with sem:
                try:
                    logger.info("Fetching: %s", url)
                    resp = await safe_get(client, url)
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "")
                    if "text/html" not in ct and "application/xhtml" not in ct:
                        logger.info("Skip non-html (%s): %s", ct, url)
                        return None
                    logger.info("Fetched OK: %s (%d bytes)", url, len(resp.text))
                    return (url, resp.text, str(resp.url))
                except Exception as e:
                    logger.warning("Fetch failed: %s — %r", url, e)
                    return None

        empty_batches = 0
        max_empty_batches = 10

        logger.info("Crawl start: %s (queue=%d)", start_normalized, len(queue))

        while queue and pages_yielded < MAX_PAGES:
            batch_size = min(MAX_CONCURRENT, len(queue), MAX_PAGES - pages_yielded)
            batch_urls = [queue.popleft() for _ in range(batch_size)]

            tasks = [asyncio.create_task(fetch_page(u)) for u in batch_urls]
            results = await asyncio.gather(*tasks)

            batch_had_result = False
            for result in results:
                if result is None:
                    continue
                url, html, final_url = result
                batch_had_result = True

                text = extract_html(html)
                if text and text.strip():
                    pages_yielded += 1
                    yield CrawledPage(url=url, text=text)

                    if pages_yielded >= MAX_PAGES:
                        break

                for link in _extract_links(html, final_url):
                    if link not in visited:
                        visited.add(link)
                        queue.append(link)

            if batch_had_result:
                empty_batches = 0
            else:
                empty_batches += 1
                logger.info("Empty batch #%d (queue=%d)", empty_batches, len(queue))
                if empty_batches >= max_empty_batches:
                    logger.info("Too many empty batches, stopping crawl")
                    break

        logger.info("Crawl done: yielded %d pages, visited %d urls", pages_yielded, len(visited))

"""Пакетный аудит сайта: краулинг + проверка + сводка по правилам/страницам."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from typing import Any

from .checker import check_text
from .crawler import crawl_site


def _snippet(text: str, line: int, fragment: str, radius: int = 140) -> str:
    lines = text.splitlines()
    if 1 <= line <= len(lines):
        source = lines[line - 1]
    else:
        source = text
    idx = source.find(fragment) if fragment else -1
    if idx < 0:
        return source[: radius * 2].strip()
    start = max(0, idx - radius)
    end = min(len(source), idx + len(fragment) + radius)
    return source[start:end].strip()


async def audit_site(url: str, max_pages: int, include_spelling: bool = False) -> dict[str, Any]:
    pages = []
    async for page in crawl_site(url):
        pages.append(page)
        if len(pages) >= max_pages:
            break

    issues: list[dict[str, Any]] = []
    for page in pages:
        page_issues = await check_text(page.text, include_spelling=include_spelling)
        for issue in page_issues:
            issue["page_url"] = page.url
            issue["snippet"] = _snippet(
                page.text,
                int(issue.get("line") or 0),
                str(issue.get("text") or ""),
            )
            issues.append(issue)

    by_rule = Counter(issue.get("registry_id") or issue.get("rule", "") for issue in issues)
    by_page = Counter(issue.get("page_url", "") for issue in issues)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        rule = issue.get("registry_id") or issue.get("rule", "")
        if len(examples[rule]) >= 8:
            continue
        examples[rule].append({
            "page_url": issue.get("page_url", ""),
            "line": issue.get("line", 0),
            "text": issue.get("text", ""),
            "rule": issue.get("rule", ""),
            "message": issue.get("message", ""),
            "snippet": issue.get("snippet", ""),
        })

    return {
        "url": url,
        "pages_checked": len(pages),
        "issues_count": len(issues),
        "by_rule": by_rule.most_common(),
        "by_page": by_page.most_common(),
        "examples": dict(examples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--include-spelling", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(audit_site(args.url, args.max_pages, args.include_spelling))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

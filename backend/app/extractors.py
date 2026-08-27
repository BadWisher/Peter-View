"""Извлечение текста из файлов (docx, html, txt) и URL."""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from docx import Document

from .net_guard import safe_get

SKIP_TAGS = frozenset((
    "script", "style", "noscript", "svg", "math",
    "iframe", "object", "embed", "canvas",
    "template", "dialog", "head", "title",
    "meta", "link", "base",
))

CHROME_TAGS = frozenset(("nav", "footer", "header", "aside"))

INLINE_TAGS = frozenset((
    "a", "abbr", "acronym", "b", "bdo", "big", "br",
    "cite", "code", "del", "dfn", "em", "i", "img",
    "ins", "kbd", "mark", "q", "s", "samp", "small",
    "span", "strong", "sub", "sup", "time", "tt",
    "u", "var", "wbr", "font", "nobr",
))

_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,:;!?])")
_SPECIAL_SPACES = str.maketrans({
    "\xa0": " ",
    "\u2009": " ",
    "\u202f": " ",
    "\u00ad": "",
})


def normalize_spaces(text: str) -> str:
    """Чистит артефакты извлечения: спецпробелы, двойные пробелы и пробел перед
    пунктуацией (его создаёт BeautifulSoup при склейке инлайновых тегов, напр.
    «<b>Слово</b>. Текст» → «Слово . Текст»)."""
    text = text.translate(_SPECIAL_SPACES)
    text = _MULTI_SPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return text.strip()


async def extract_from_file(content: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()

    if ext == ".txt":
        return content.decode("utf-8", errors="replace")
    if ext == ".docx":
        return _extract_docx(content)
    if ext in (".html", ".htm"):
        return extract_html(content.decode("utf-8", errors="replace"))
    if ext == ".md":
        return _extract_markdown(content.decode("utf-8", errors="replace"))

    raise ValueError(f"Неподдерживаемый формат файла: {ext}")


_MD_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MD_HR = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_MD_LIST = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_MD_OLIST = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_MD_HTML = re.compile(r"<[^>]+>")


def _extract_markdown(text: str) -> str:
    text = _MD_CODE_BLOCK.sub("", text)
    text = _MD_INLINE_CODE.sub(r"\1", text)
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _MD_ITALIC.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _MD_HR.sub("", text)
    text = _MD_BLOCKQUOTE.sub("", text)
    text = _MD_LIST.sub("", text)
    text = _MD_OLIST.sub("", text)
    text = _MD_HTML.sub("", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# Лимиты против zip-бомб в docx (docx — это zip-архив).
_ZIP_MAX_UNCOMPRESSED = int(os.getenv("DOCX_MAX_UNCOMPRESSED_BYTES", str(300 * 1024 * 1024)))
_ZIP_MAX_RATIO = int(os.getenv("DOCX_MAX_COMPRESSION_RATIO", "200"))
_ZIP_MAX_ENTRIES = int(os.getenv("DOCX_MAX_ENTRIES", "2000"))


def assert_docx_safe(content: bytes) -> None:
    """Проверяет docx-архив на zip-бомбу до распаковки python-docx."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infos = zf.infolist()
            if len(infos) > _ZIP_MAX_ENTRIES:
                raise ValueError("Слишком много файлов внутри документа")
            total_uncompressed = sum(i.file_size for i in infos)
            total_compressed = sum(i.compress_size for i in infos) or 1
            if total_uncompressed > _ZIP_MAX_UNCOMPRESSED:
                raise ValueError("Документ распаковывается в слишком большой объём")
            if total_uncompressed / total_compressed > _ZIP_MAX_RATIO:
                raise ValueError("Подозрительная степень сжатия документа")
    except zipfile.BadZipFile:
        raise ValueError("Файл не является корректным docx")


def _extract_docx(content: bytes) -> str:
    assert_docx_safe(content)
    doc = Document(io.BytesIO(content))
    parts: list[str] = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1]
        if tag == "p":
            text = element.text or ""
            for run in element.iter():
                if run.tag.endswith("}t"):
                    text = ""
                    break
            paragraph_text = ""
            for node in element.iter():
                if node.tag.endswith("}t") and node.text:
                    paragraph_text += node.text
            paragraph_text = paragraph_text.strip()
            if paragraph_text:
                parts.append(paragraph_text)
        elif tag == "tbl":
            _extract_docx_table(element, parts)

    return "\n".join(parts)


def _extract_docx_table(tbl_element, parts: list[str]) -> None:
    """Извлекает текст из таблицы docx, строка за строкой."""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for tr in tbl_element.findall(f"{ns}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{ns}tc"):
            cell_text = ""
            for p in tc.findall(f"{ns}p"):
                for node in p.iter(f"{ns}t"):
                    if node.text:
                        cell_text += node.text
            cell_text = cell_text.strip()
            if cell_text:
                cells.append(cell_text)
            for nested_tbl in tc.findall(f"{ns}tbl"):
                _extract_docx_table(nested_tbl, parts)
        if cells:
            parts.append(" | ".join(cells))


def extract_html(html: str, include_chrome: bool = False) -> str:
    """Видимый текст из HTML, блочные элементы → отдельные строки."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(SKIP_TAGS):
        tag.decompose()
    if not include_chrome:
        for tag in soup.find_all(CHROME_TAGS):
            tag.decompose()

    hidden_style = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
    for tag in soup.find_all(attrs={"style": hidden_style}):
        tag.decompose()
    for tag in soup.find_all(attrs={"hidden": True}):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    nav_patterns = re.compile(
        r"breadcrumb|menuparent|nav-bar|navbar|menu-main|main-menu|"
        r"site-nav|top-nav|footer-nav|header-menu|cookie",
        re.I,
    )
    if not include_chrome:
        for tag in soup.find_all(class_=nav_patterns):
            tag.decompose()
        for tag in soup.find_all(id=nav_patterns):
            tag.decompose()
        for tag in soup.find_all(attrs={"role": re.compile(r"navigation|banner", re.I)}):
            tag.decompose()

    lines: list[str] = []
    body = soup.find("body") or soup
    _walk(body, lines)

    text = "\n".join(lines).translate(_SPECIAL_SPACES)
    text = _MULTI_NL.sub("\n\n", text)
    text = "\n".join(
        _SPACE_BEFORE_PUNCT.sub(r"\1", _MULTI_SPACE.sub(" ", line)).strip()
        for line in text.splitlines()
    )
    return text.strip()


def _is_inline(tag: Tag) -> bool:
    if tag.name == "a":
        return not _has_any_block_child(tag)
    return tag.name in INLINE_TAGS


def _collect_inline_text(node) -> str:
    """Собираем текст из инлайновых тегов в одну строку."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    parts = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and _is_inline(child):
            parts.append(_collect_inline_text(child))
    return "".join(parts)


def _has_any_block_child(tag: Tag) -> bool:
    for child in tag.children:
        if isinstance(child, Tag) and not _is_inline(child):
            return True
    return False


def _walk(node, lines: list[str]):
    if isinstance(node, NavigableString):
        text = _MULTI_SPACE.sub(" ", str(node)).strip()
        if text:
            lines.append(text)
        return

    if not isinstance(node, Tag):
        return

    if _is_inline(node):
        text = _collect_inline_text(node)
        text = _MULTI_SPACE.sub(" ", text).strip()
        if text:
            lines.append(text)
        return

    if not _has_any_block_child(node):
        text = node.get_text(separator=" ", strip=True)
        text = _MULTI_SPACE.sub(" ", text)
        if text:
            lines.append(text)
        return

    for child in node.children:
        _walk(child, lines)


async def extract_from_url(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Proofreader/1.0)"},
    ) as client:
        resp = await safe_get(client, url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "text/html" in content_type or "application/xhtml" in content_type:
            return extract_html(resp.text)

        return resp.text

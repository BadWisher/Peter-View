"""Обёртка над Vale CLI: пишем текст во временный файл, парсим JSON-вывод."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .style_guide_registry import enabled_vale_rule_ids


@dataclass
class ValeIssue:
    line: int
    column: int
    end_column: int
    text: str
    rule: str
    message: str
    severity: str
    replacement: str = ""


VALE_DIR = Path(__file__).resolve().parent.parent / "vale"
ENABLED_CHECKS = enabled_vale_rule_ids()
UNIT_SLASH_RE = re.compile(r"^(?:[кмгтКМГТ]?[бБ]ит|[кмгтКМГТ]?[бБ]|байт|бит)/с$")
CLICK_ALLOWED_RE = re.compile(r"^отклик[а-яё]*$", re.IGNORECASE)
LETTER_YO_ALLOWED = {"её", "ею", "всё", "все"}
QUOTED_LATIN_ACRONYM_RE = re.compile(r"^[«„\"][A-Z0-9]{2,8}[»”\"]$")


def _line_col(full_text: str, char_offset: int) -> tuple[int, int]:
    line = full_text.count("\n", 0, char_offset) + 1
    last_nl = full_text.rfind("\n", 0, char_offset)
    col = char_offset - last_nl
    return line, col


def _line_text(text: str, line_num: int) -> str:
    lines = text.splitlines()
    if 1 <= line_num <= len(lines):
        return lines[line_num - 1].strip()
    return ""


def _sentence_around_column(text: str, line_num: int, column: int) -> str:
    line_text = _line_text(text, line_num)
    if not line_text:
        return ""
    idx = max(0, min(len(line_text), column - 1))
    start_candidates = [line_text.rfind(mark, 0, idx) for mark in ".!?"]
    start = max(start_candidates) + 1
    end_candidates = [pos for mark in ".!?" if (pos := line_text.find(mark, idx)) >= 0]
    end = min(end_candidates) + 1 if end_candidates else len(line_text)
    return line_text[start:end].strip()


def _word_around_column(text: str, line_num: int, column: int) -> str:
    line_text = _line_text(text, line_num)
    if not line_text:
        return ""
    idx = max(0, min(len(line_text) - 1, column - 1))
    start = idx
    while start > 0 and not line_text[start - 1].isspace():
        start -= 1
    end = idx + 1
    while end < len(line_text) and not line_text[end].isspace():
        end += 1
    word = line_text[start:end].strip()
    return word.replace("\u00ad", "[мягкий перенос U+00AD]")


async def run_vale(text: str) -> list[ValeIssue]:
    """Пишем текст в tmpfile → vale --output JSON → парсим результат."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        if text and not text.endswith("\n"):
            f.write("\n")
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "vale",
            "--output", "JSON",
            "--config", str(VALE_DIR / ".vale.ini"),
            tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(VALE_DIR),
        )
        stdout, stderr = await proc.communicate()

        if not stdout.strip():
            return []

        try:
            data = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            return []

        issues: list[ValeIssue] = []
        for filepath, file_issues in data.items():
            for item in file_issues:
                replacement = ""
                if item.get("Action", {}).get("Name") == "replace":
                    params = item["Action"].get("Params", [])
                    if params:
                        replacement = params[0]

                check = item.get("Check", "")
                if check not in ENABLED_CHECKS:
                    continue

                line = item.get("Line", 0)
                column = item.get("Span", [0, 0])[0]
                end_column = item.get("Span", [0, 0])[1]
                matched_text = item.get("Match", "")
                if check == "RuStyleGuide.Slash_Words" and UNIT_SLASH_RE.match(matched_text):
                    continue
                if check == "RuStyleGuide.UITerms_Click" and CLICK_ALLOWED_RE.match(matched_text):
                    continue
                if check == "RuStyleGuide.LetterYo" and matched_text.lower() in LETTER_YO_ALLOWED:
                    continue
                if check == "RuStyleGuide.Quotes_LatinInQuotes" and QUOTED_LATIN_ACRONYM_RE.match(matched_text):
                    continue
                if line <= 0 and matched_text:
                    match_offset = text.find(matched_text)
                    if match_offset >= 0:
                        line, column = _line_col(text, match_offset)
                        end_column = column + len(matched_text)
                if check == "RuStyleGuide.Dash_EmDash" and line > 0:
                    sentence = _sentence_around_column(text, line, column)
                    matched_text = sentence or matched_text
                    replacement = "– (U+2013)"
                    item["Message"] = (
                        "Найдено длинное тире U+2014 «—». "
                        f"Используйте среднее тире U+2013 «–». Позиция в строке: {column}."
                    )
                if check == "RuStyleGuide.Formatting_SoftHyphen" and line > 0:
                    matched_text = _word_around_column(text, line, column) or "мягкий перенос U+00AD"
                    replacement = "удалить U+00AD"

                issues.append(ValeIssue(
                    line=line,
                    column=column,
                    end_column=end_column,
                    text=matched_text,
                    rule=check,
                    message=item.get("Message", ""),
                    severity=item.get("Severity", "warning"),
                    replacement=replacement,
                ))
        return issues
    finally:
        os.unlink(tmp_path)

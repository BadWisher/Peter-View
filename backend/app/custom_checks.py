"""
Морфологические проверки на pymorphy3 + razdel.

Покрывает то, что Vale регулярками не вытянет:
пассивный залог, антропоморфизм, длина предложения,
«Вы» с заглавной, согласование прил./сущ. и подл./сказ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

import pymorphy3
from razdel import sentenize, tokenize

morph = pymorphy3.MorphAnalyzer()

TECH_SUBJECT_LEMMAS: set[str] = {
    "компьютер", "программа", "система", "приложение", "сервис",
    "сервер", "модуль", "компонент", "функция", "алгоритм",
    "процесс", "устройство", "оборудование", "платформа",
    "интерфейс", "утилита", "скрипт", "драйвер", "ядро",
    "база", "браузер", "контроллер", "маршрутизатор", "коммутатор",
    "фильтр", "детектор", "сенсор", "коллектор", "агент",
    "демон", "служба", "сервлет", "микросервис", "библиотека",
    "фреймворк", "плагин", "расширение", "протокол", "движок",
    "обработчик", "планировщик", "балансировщик", "прокси",
    "антивирус", "файрвол", "брандмауэр",
}

HUMAN_VERB_LEMMAS: set[str] = {
    "видеть", "увидеть", "знать", "узнать", "познать",
    "думать", "подумать", "размышлять", "считать", "полагать",
    "понимать", "понять", "осознать", "осознавать",
    "хотеть", "захотеть", "желать", "пожелать",
    "решить", "решать", "решиться",
    "помнить", "запомнить", "вспомнить", "вспоминать",
    "забыть", "забывать", "позабыть",
    "чувствовать", "почувствовать", "ощущать", "ощутить",
    "верить", "поверить", "доверять",
    "научиться", "учиться", "выучить",
    "догадаться", "догадываться",
    "стремиться", "стараться", "постараться",
    "бояться", "испугаться", "опасаться",
    "радоваться", "обрадоваться",
    "переживать", "волноваться", "беспокоиться",
    "сердиться", "рассердиться", "злиться", "разозлиться",
    "любить", "полюбить", "нравиться", "понравиться",
    "ненавидеть", "возненавидеть",
    "надеяться", "понадеяться",
    "мечтать", "помечтать",
    "сомневаться", "засомневаться",
    "удивиться", "удивляться",
    "обидеться", "обижаться",
    "гордиться",
    "стыдиться",
    "завидовать", "позавидовать",
    "скучать", "соскучиться",
    "уставать", "устать",
}

FORMAL_YOU_WORDS = {"Вы", "Ваш", "Ваша", "Ваше", "Ваши", "Вас", "Вам", "Вами"}
FORMAL_YOU_LEMMAS = {"вы", "ваш"}
AGREEMENT_SKIP_LEMMAS = {
    "который", "какой", "такой", "этот", "тот", "весь", "самый",
    "мой", "твой", "наш", "ваш", "свой", "его", "ее", "их",
}

BYRE_LEMMA = "быть"

MAX_SENTENCE_WORDS = 25


@dataclass
class Issue:
    line: int
    column: int
    end_column: int
    text: str
    rule: str
    message: str
    severity: str  # "error" | "warning" | "suggestion"
    replacement: str = ""


def _line_col(full_text: str, char_offset: int) -> tuple[int, int]:
    """Смещение в символах → (строка, колонка), нумерация с 1."""
    line = full_text.count("\n", 0, char_offset) + 1
    last_nl = full_text.rfind("\n", 0, char_offset)
    col = char_offset - last_nl  # 1-based
    return line, col


def _best_parse(word: str):
    """Первый (наиболее вероятный) разбор pymorphy3."""
    parses = morph.parse(word)
    return parses[0] if parses else None


def check_passive_voice(text: str) -> list[Issue]:
    """Пассивный залог: «быть» + краткое причастие (PRTS)."""
    issues: list[Issue] = []
    for sent in sentenize(text):
        tokens = list(tokenize(sent.text))
        for i in range(len(tokens) - 1):
            t_cur = tokens[i]
            t_next = tokens[i + 1]

            word_cur = t_cur.text
            word_next = t_next.text

            if not word_cur[0].isalpha() or not word_next[0].isalpha():
                continue

            p_cur = _best_parse(word_cur)
            if p_cur is None:
                continue

            if p_cur.normal_form != BYRE_LEMMA:
                continue
            if "VERB" not in p_cur.tag and "INFN" not in p_cur.tag:
                continue

            p_next = _best_parse(word_next)
            if p_next is None:
                continue

            if "PRTS" in p_next.tag:
                abs_start = sent.start + t_cur.start
                abs_end = sent.start + t_next.stop
                fragment = text[abs_start:abs_end]
                line, col = _line_col(text, abs_start)
                _, end_col = _line_col(text, abs_end)
                issues.append(Issue(
                    line=line,
                    column=col,
                    end_column=end_col,
                    text=fragment,
                    rule="RuStyleGuide.PassiveVoice",
                    message=(
                        "Пассивный залог. Используйте активный залог: "
                        "подлежащее должно выполнять действие."
                    ),
                    severity="warning",
                ))
    return issues


def check_anthropomorphism(text: str) -> list[Issue]:
    """Антропоморфизм: человеческий глагол при техническом подлежащем."""
    issues: list[Issue] = []
    for sent in sentenize(text):
        tokens = list(tokenize(sent.text))
        parsed = []
        for t in tokens:
            if t.text[0].isalpha():
                p = _best_parse(t.text)
                parsed.append((t, p))
            else:
                parsed.append((t, None))

        subject_positions: list[int] = []
        for idx, (tok, p) in enumerate(parsed):
            if p is None:
                continue
            if p.normal_form in TECH_SUBJECT_LEMMAS and "NOUN" in p.tag:
                subject_positions.append(idx)

        for subj_idx in subject_positions:
            for verb_idx in range(subj_idx + 1, min(subj_idx + 5, len(parsed))):
                tok_v, p_v = parsed[verb_idx]
                if p_v is None:
                    continue
                if "VERB" not in p_v.tag and "INFN" not in p_v.tag:
                    continue
                if p_v.normal_form in HUMAN_VERB_LEMMAS:
                    subj_tok = parsed[subj_idx][0]
                    abs_start = sent.start + subj_tok.start
                    abs_end = sent.start + tok_v.stop
                    fragment = text[abs_start:abs_end]
                    line, col = _line_col(text, abs_start)
                    _, end_col = _line_col(text, abs_end)
                    issues.append(Issue(
                        line=line,
                        column=col,
                        end_column=end_col,
                        text=fragment,
                        rule="RuStyleGuide.Anthropomorphism",
                        message=(
                            "Антропоморфизм. Не приписывайте человеческие "
                            "качества программному обеспечению или оборудованию."
                        ),
                        severity="warning",
                    ))
                    break
    return issues


def check_sentence_length(text: str) -> list[Issue]:
    """Длинные предложения (> MAX_SENTENCE_WORDS слов). Каждая строка отдельно,
    чтобы заголовки не склеивались с телом."""
    issues: list[Issue] = []
    line_offset = 0
    for text_line in text.split("\n"):
        if text_line.strip():
            for sent in sentenize(text_line):
                words = [t for t in tokenize(sent.text) if t.text[0].isalpha()]
                if len(words) > MAX_SENTENCE_WORDS:
                    abs_start = line_offset + sent.start
                    abs_end = line_offset + sent.stop
                    line, col = _line_col(text, abs_start)
                    _, end_col = _line_col(text, abs_end)
                    issues.append(Issue(
                        line=line,
                        column=col,
                        end_column=end_col,
                        text=sent.text.strip(),
                        rule="RuStyleGuide.SentenceLength",
                        message=(
                            f"Предложение содержит {len(words)} слов "
                            f"(рекомендуется не более {MAX_SENTENCE_WORDS}). "
                            "Разбейте на несколько коротких предложений."
                        ),
                        severity="warning",
                    ))
        line_offset += len(text_line) + 1
    return issues


def check_formal_you(text: str) -> list[Issue]:
    """«Вы/Ваш/...» с заглавной не в начале предложения."""
    issues: list[Issue] = []
    line_offset = 0
    for text_line in text.split("\n"):
        if text_line.strip():
            for sent in sentenize(text_line):
                tokens = list(tokenize(sent.text))
                alpha_tokens = [(i, t) for i, t in enumerate(tokens) if t.text[0].isalpha()]
                if not alpha_tokens:
                    continue

                first_alpha_idx = alpha_tokens[0][0]

                for orig_idx, tok in alpha_tokens:
                    if not tok.text[0].isupper():
                        continue
                    p = _best_parse(tok.text)
                    if p is None or p.normal_form not in FORMAL_YOU_LEMMAS:
                        continue
                    if orig_idx == first_alpha_idx:
                        continue

                    abs_start = line_offset + sent.start + tok.start
                    abs_end = line_offset + sent.start + tok.stop
                    line, col = _line_col(text, abs_start)
                    _, end_col = _line_col(text, abs_end)
                    replacement = tok.text[0].lower() + tok.text[1:]
                    issues.append(Issue(
                        line=line,
                        column=col,
                        end_column=end_col,
                        text=tok.text,
                        rule="RuStyleGuide.FormalYou",
                        message=(
                            f"Местоимение «{tok.text}» пишется со строчной буквы: "
                            f"«{replacement}»."
                        ),
                        severity="error",
                        replacement=replacement,
                    ))
        line_offset += len(text_line) + 1
    return issues


def check_adj_noun_agreement(text: str) -> list[Issue]:
    issues: list[Issue] = []
    line_offset = 0
    for text_line in text.split("\n"):
        if not text_line.strip():
            line_offset += len(text_line) + 1
            continue
        tokens = [t for t in tokenize(text_line) if t.text and t.text[0].isalpha()]
        if len(tokens) != 2:
            line_offset += len(text_line) + 1
            continue
        for idx, (left, right) in enumerate(zip(tokens, tokens[1:])):
            if idx > 0 and tokens[idx - 1].text.lower() in {"и", "или"}:
                continue
            left_parses = [p for p in morph.parse(left.text) if "ADJF" in p.tag or "PRTF" in p.tag]
            right_parses = [p for p in morph.parse(right.text) if "NOUN" in p.tag]
            if not left_parses or not right_parses:
                continue
            if any(p.normal_form in AGREEMENT_SKIP_LEMMAS for p in left_parses):
                continue
            if any(_adj_noun_agree(p_left, p_right) for p_left in left_parses for p_right in right_parses):
                continue

            abs_start = line_offset + left.start
            abs_end = line_offset + right.stop
            fragment = text[abs_start:abs_end]
            line, col = _line_col(text, abs_start)
            _, end_col = _line_col(text, abs_end)
            issues.append(Issue(
                line=line,
                column=col,
                end_column=end_col,
                text=fragment,
                rule="RuStyleGuide.Agreement",
                message="Проверьте согласование прилагательного и существительного.",
                severity="warning",
            ))
        line_offset += len(text_line) + 1
    return issues


def check_subject_verb_agreement(text: str) -> list[Issue]:
    issues: list[Issue] = []
    line_offset = 0
    for text_line in text.split("\n"):
        tokens = [t for t in tokenize(text_line) if t.text and t.text[0].isalpha()]
        parsed = [(t, _best_parse(t.text)) for t in tokens]
        for idx, (tok, parse) in enumerate(parsed):
            verb_parses = [p for p in morph.parse(tok.text) if "VERB" in p.tag]
            if not verb_parses:
                continue
            if any(p.tag.number == "plur" for p in verb_parses):
                continue
            if not any(p.tag.number == "sing" for p in verb_parses):
                continue
            window = parsed[max(0, idx - 4):idx]
            plural_nouns = [
                prev_tok
                for prev_tok, prev_parse in window
                if prev_parse is not None
                and "NOUN" in prev_parse.tag
                and prev_parse.tag.number == "plur"
                and prev_parse.tag.case == "nomn"
            ]
            if not plural_nouns:
                continue
            subject = plural_nouns[-1]
            between = text_line[subject.stop:tok.start].lower()
            if any(mark in between for mark in (".", "!", "?", ",", ";", ":")):
                continue
            if re.search(r"\b(?:и|или)\b", between):
                continue
            if any(
                prev_parse is not None
                and "NOUN" in prev_parse.tag
                and prev_parse.tag.number == "sing"
                and prev_parse.tag.case == "nomn"
                for prev_tok, prev_parse in window
                if prev_tok.start < subject.start
            ):
                continue
            abs_start = line_offset + subject.start
            abs_end = line_offset + tok.stop
            fragment = text[abs_start:abs_end]
            line, col = _line_col(text, abs_start)
            _, end_col = _line_col(text, abs_end)
            issues.append(Issue(
                line=line,
                column=col,
                end_column=end_col,
                text=fragment,
                rule="RuStyleGuide.SubjectVerbAgreement",
                message="Проверьте согласование подлежащего и сказуемого в числе.",
                severity="warning",
            ))
        line_offset += len(text_line) + 1
    return issues


def _adj_noun_agree(p_left, p_right) -> bool:
    if p_left.tag.case != p_right.tag.case:
        return False
    if p_left.tag.number != p_right.tag.number:
        return False
    if p_left.tag.number == "sing" and p_left.tag.gender != p_right.tag.gender:
        return False
    return True


def run_all_custom_checks(text: str) -> list[Issue]:
    """Все активные кастомные проверки разом."""
    issues: list[Issue] = []
    issues.extend(check_anthropomorphism(text))
    issues.extend(check_sentence_length(text))
    issues.extend(check_formal_you(text))
    issues.extend(check_adj_noun_agreement(text))
    issues.extend(check_subject_verb_agreement(text))
    return issues

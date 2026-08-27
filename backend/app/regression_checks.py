"""Регрессионные тесты: каждый кейс проверяет, что правила не сломались."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .checker import check_text


@dataclass(frozen=True)
class RegressionCase:
    name: str
    text: str
    expect_rules: set[str] = field(default_factory=set)
    forbid_rules: set[str] = field(default_factory=set)
    forbid_texts: set[str] = field(default_factory=set)


CASES: list[RegressionCase] = [
    RegressionCase(
        name="dash: long dash is reported, en dash is accepted",
        text="Система — это решение. Сервис – это компонент.",
        expect_rules={"RuStyleGuide.Dash_EmDash"},
        forbid_texts={"–", "— (U+2014)", "[— U+2014]"},
    ),
    RegressionCase(
        name="dash: en dash alone is not reported",
        text="Сервис – это компонент.",
        forbid_rules={"RuStyleGuide.Dash_EmDash"},
        forbid_texts={"–", "– (U+2013)"},
    ),
    RegressionCase(
        name="dash: hyphenated technical compounds are accepted",
        text="Прокси-сервер отправляет трафик в дата-центр.",
        forbid_rules={"RuStyleGuide.Dash_HyphenSpace", "RuStyleGuide.Dash_NoSpace"},
    ),
    RegressionCase(
        name="addressing: uppercase formal you is reported",
        text="Проверьте Ваши записи.",
        expect_rules={"RuStyleGuide.FormalYou"},
    ),
    RegressionCase(
        name="addressing: uppercase formal you oblique form is reported",
        text="Решение вписывается в Вашу инфраструктуру.",
        expect_rules={"RuStyleGuide.FormalYou"},
    ),
    RegressionCase(
        name="addressing: uppercase formal you at line start is accepted",
        text="Вы получаете специальные условия.\nВы получаете часть дохода.",
        forbid_rules={"RuStyleGuide.FormalYou"},
    ),
    RegressionCase(
        name="addressing: наш is not a hard automatic check",
        text="Наш продукт помогает пользователю. Наши сервисы доступны.",
        forbid_rules={"RuStyleGuide.Possessives"},
    ),
    RegressionCase(
        name="passive voice remains manual",
        text="Код для авторизации был отправлен в SMS.",
        forbid_rules={"RuStyleGuide.PassiveVoice"},
    ),
    RegressionCase(
        name="technical spelling terms are filtered by lemma and context",
        text="Ботнеты используют терабитные каналы медиаресурсов. Нетарифицируемый трафик доступен в тарифе. Высоконагруженной системе нужен мониторинг киберугроз. Система работает проактивно и использует проактивной стратегии.",
        forbid_texts={"Ботнеты", "терабитные", "медиаресурсов", "Нетарифицируемый", "Высоконагруженной", "киберугроз", "проактивно", "проактивной"},
    ),
    RegressionCase(
        name="technical productive terms are not spelling errors",
        text="Кибербезопасности помогает мультивекторной защите после пересборки сервиса. Авторитативный сервер отвечает на DNS-запросы. Многовекторным атакам противостоят компании финтеха.",
        forbid_rules={"LanguageTool.ru"},
        forbid_texts={"Кибербезопасности", "мультивекторной", "пересборки", "Авторитативный", "Многовекторным", "финтеха"},
    ),
    RegressionCase(
        name="technical loanwords are style issues, not spelling",
        text="Резолвер может логировать DNS-запросы. Технологии вендора помогают команде.",
        expect_rules={"RuStyleGuide.Anglicisms"},
        forbid_rules={"LanguageTool.ru"},
    ),
    RegressionCase(
        name="glossary still works as generalized substitution",
        text="Укажите email в поле.",
        expect_rules={"RuStyleGuide.Glossary"},
    ),
    RegressionCase(
        name="glossary: latin web prefix is replaced",
        text="Для защиты web-серверов используется отдельный тариф.",
        expect_rules={"RuStyleGuide.Terminology_WebPrefix"},
    ),
    RegressionCase(
        name="sentence length is based on guide threshold",
        text="Откройте раздел, выберите нужный элемент, настройте параметры, сохраните изменения, проверьте результат выполнения операции в личном кабинете, добавьте комментарий, приложите файл и отправьте подробный отчет администратору проекта.",
        expect_rules={"RuStyleGuide.SentenceLength"},
    ),
    RegressionCase(
        name="sentence length accepts 25 words",
        text="Откройте раздел, выберите нужный элемент, настройте параметры, сохраните изменения и проверьте результат выполнения операции в личном кабинете.",
        forbid_rules={"RuStyleGuide.SentenceLength"},
    ),
    RegressionCase(
        name="typography: visible double spaces are reported",
        text="Проконсультируйтесь  с экспертом.",
        expect_rules={"RuStyleGuide.Spacing_Double"},
    ),
    RegressionCase(
        name="site grammar: bez plus gerund is reported",
        text="Эффективная защита без нарушая принципов сквозного шифрования.",
        expect_rules={"RuStyleGuide.Grammar_BezGerund"},
    ),
    RegressionCase(
        name="grammar: adjective noun agreement is reported",
        text="Асимметричная фильтрации.",
        expect_rules={"RuStyleGuide.Agreement"},
    ),
    RegressionCase(
        name="grammar: correct adjective noun agreement is accepted",
        text="Асимметричная фильтрация.",
        forbid_rules={"RuStyleGuide.Agreement"},
    ),
    RegressionCase(
        name="grammar: agreement check does not inspect normal sentences",
        text="Локальное и облачное развертывание решений. Используйте фильтр для атак, перегружающих сервер.",
        forbid_rules={"RuStyleGuide.Agreement"},
    ),
    RegressionCase(
        name="grammar: allowed ellipsis with protocol is accepted",
        text="Размер пакета больше допустимого протоколом IPv4.",
        forbid_rules={"LanguageTool.ru"},
    ),
    RegressionCase(
        name="grammar: plural subject singular verb is reported",
        text="Все компоненты защиты находится в облачной инфраструктуре.",
        expect_rules={"RuStyleGuide.SubjectVerbAgreement"},
    ),
    RegressionCase(
        name="grammar: plural subject plural verb is accepted",
        text="Все компоненты защиты находятся в облачной инфраструктуре.",
        forbid_rules={"RuStyleGuide.SubjectVerbAgreement"},
    ),
    RegressionCase(
        name="grammar: subject verb check ignores coordination",
        text="Появляются новые типы атак и ботов, снижается стоимость их организации. Команда исследует новые типы атак и обновляет механизмы защиты.",
        forbid_rules={"RuStyleGuide.SubjectVerbAgreement"},
    ),
    RegressionCase(
        name="grammar: subject verb check stays inside sentence",
        text="Администраторы успевают отреагировать. Сервер остается уязвимым. Правила настраиваются под требования бизнеса. API интегрируется в инфраструктуру.",
        forbid_rules={"RuStyleGuide.SubjectVerbAgreement"},
    ),
    RegressionCase(
        name="grammar: plural subject plural verb is accepted by parse alternatives",
        text="В финальной части мероприятия эксперты перешли к формату общения.",
        forbid_rules={"RuStyleGuide.SubjectVerbAgreement"},
    ),
    RegressionCase(
        name="grammar: subject verb check respects singular head noun",
        text="Использование этой технологии не требует передачи сертификата.",
        forbid_rules={"RuStyleGuide.SubjectVerbAgreement"},
    ),
    RegressionCase(
        name="site punctuation: slash between words is reported",
        text="Решение работает в сети клиента/партнера.",
        expect_rules={"RuStyleGuide.Slash_Words"},
    ),
    RegressionCase(
        name="site punctuation: URL slash is not reported as word slash",
        text="Откройте https://example.com/folder/page.html.",
        forbid_rules={"RuStyleGuide.Slash_Words"},
    ),
    RegressionCase(
        name="site punctuation: units with slash are not reported",
        text="Полоса легитимного трафика составляет 10 Мбит/с.",
        forbid_rules={"RuStyleGuide.Slash_Words"},
    ),
    RegressionCase(
        name="site punctuation: level ranges with en dash are accepted",
        text="Защита работает на уровнях L3–L7.",
        forbid_rules={"RuStyleGuide.Dash_NoSpace"},
    ),
    RegressionCase(
        name="site formatting: service line separator is reported",
        text="Балансировка трафика осуществляется на двух этапах:\u2028до фильтрации.",
        expect_rules={"RuStyleGuide.Formatting_LineSeparator"},
    ),
    RegressionCase(
        name="site formatting: soft hyphen is not reported automatically",
        text="Многопользова\u00adтельское управление.",
        forbid_rules={"RuStyleGuide.Formatting_SoftHyphen"},
        forbid_texts={"\u00ad", "Многопользова[мягкий перенос U+00AD]тельское"},
    ),
    RegressionCase(
        name="letter yo: documented ambiguity exceptions are accepted",
        text="Её задача — защитить ресурс. Всё работает корректно.",
        forbid_rules={"RuStyleGuide.LetterYo"},
    ),
    RegressionCase(
        name="product name: ddos casing is reported",
        text="Сертификат качества Kaspersky DDOS Protection.",
        expect_rules={"RuStyleGuide.ProductNames"},
    ),
    RegressionCase(
        name="product name: missing space in Kaspersky DDoS is reported",
        text="Личный кабинет KasperskyDDoS Protection.",
        expect_rules={"RuStyleGuide.ProductNames"},
    ),
    RegressionCase(
        name="site terminology: apostrophe with cyrillic ending is reported",
        text="Телеком-отрасль на прицеле у DDoS’еров.",
        expect_rules={"RuStyleGuide.Apostrophe_CyrillicEnding"},
    ),
    RegressionCase(
        name="site terminology: english apostrophe is not reported",
        text="Сертификат Let’s Encrypt обновляется автоматически.",
        forbid_rules={"RuStyleGuide.Apostrophe_CyrillicEnding"},
    ),
    RegressionCase(
        name="quotes: quoted technical acronym is accepted",
        text="Откройте раздел «TLS».",
        forbid_rules={"RuStyleGuide.Quotes_LatinInQuotes"},
    ),
    RegressionCase(
        name="ui terms: response time is not a click action",
        text="Сервис проверяет время отклика ресурсов.",
        forbid_rules={"RuStyleGuide.UITerms_Click"},
    ),
    RegressionCase(
        name="ui terms: actual click action is reported",
        text="Кликните на кнопку Выйти.",
        expect_rules={"RuStyleGuide.UITerms_Click"},
    ),
    RegressionCase(
        name="abbreviations: common approved abbreviations are accepted",
        text="СМИ сообщили о сертификации ФСТЭК. ООО «Модель защиты» использует WAF и CDN.",
        forbid_rules={"RuStyleGuide.Abbreviations"},
    ),
    RegressionCase(
        name="bureaucracy: forms of to be are accepted",
        text="DDoS-атаки являются причиной недоступности ресурса.",
        forbid_rules={"RuStyleGuide.Bureaucracy"},
    ),
    RegressionCase(
        name="spelling layer: legit users typo is reported",
        text="Только легимитные пользователи подключаются к ресурсу.",
        expect_rules={"LanguageTool.ru"},
    ),
]


async def run_regression() -> int:
    failures: list[str] = []

    for case in CASES:
        issues = await check_text(case.text)
        rules = {issue.get("registry_id") or issue.get("rule") for issue in issues}
        texts = {issue.get("text") for issue in issues}

        missing = case.expect_rules - rules
        forbidden_rules = case.forbid_rules & rules
        forbidden_texts = case.forbid_texts & texts

        if missing:
            failures.append(f"{case.name}: missing rules {sorted(missing)}")
        if forbidden_rules:
            failures.append(f"{case.name}: forbidden rules {sorted(forbidden_rules)}")
        if forbidden_texts:
            failures.append(f"{case.name}: forbidden texts {sorted(forbidden_texts)}")

    if failures:
        print("Regression failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Regression passed: {len(CASES)} cases")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run_regression()))


if __name__ == "__main__":
    main()

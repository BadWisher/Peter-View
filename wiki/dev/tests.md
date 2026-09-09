# Тесты и регрессия

Проверки делятся на три слоя с разной ценой запуска: быстрые unit-тесты pytest, 44 кейса регрессии правил внутри контейнера, и eval эталонных текстов против живой модели. CI безусловно гоняет первые два, eval запускается вручную.

## Запуск

```bash
make test          # pytest -q из корня репозитория
make lint          # ruff (в CI выборка жёстче: E9,F63,F7,F82)
make regression    # 44 кейса правил в контейнере backend (зависит от LanguageTool)
make ci-local      # lint + test + валидация compose + docker compose build
```

Конфигурация pytest в корневом `pyproject.toml`: `pythonpath=["backend"]`, `testpaths=["backend/tests"]`, поэтому запуск из корня, conftest.py нет. Нужны зависимости `backend/requirements-dev.txt` (pytest, pytest-asyncio, ruff). Внутри контейнера то же самое: `docker compose exec backend python -m pytest`.

## Unit-тесты: 10 файлов, 103 теста

| Файл | Строк | Покрывает |
|---|---|---|
| `test_auth_roles.py` | 101 | сидинг админа, легаси-хеш → роль admin, защита последнего админа, флаги FEATURE_* по умолчанию выключены, пустые дефолты LLM-настроек, журнал audit |
| `test_documents.py` | 165 | разбор docx/html/md/txt в блоки: списки с метаданными, таблицы, ссылки, spans форматирования, границы JSON-выдержки |
| `test_chunking.py` | 65 | размеры чанков, overlap, атомарность «введение+список», compress-каркас |
| `test_v2_pipeline_contracts.py` | 330 | контракты v2: гейт стадий по env, дедуп кандидатов, вердикты верификатора accept/reject, дроп по constraints схемы, атрибуция токенов через contextvars, сравнение ключей в теневом режиме |
| `test_styleguide_consistency.py` | 82 | `styleguide/rules.yaml` против `style_guide_registry.RULES`: id, поля, severity не разъехались |
| `test_styleguide_authority_rag_20260724.py` | 179 | приоритет правил, гибрид-RAG с boosts (numpy мок), сидинг хранилища гайдов |
| `test_styleguide_extractor.py` | 131 | экстрактор гайда из DOCX: деление на куски, merge/дедуп, лексикон, учёт частичных провалов |
| `test_watch.py` | 563 | вся подсистема мониторинга: store CRUD и retention, шифрование паролей round-trip, форма-логин, стабильность fingerprint, текстовые хунки и word-marks, kinds UI-событий, пустой снимок = ошибка, HTML-копия (скрипты вырезаны, marks, ghosts, клик-заморозка, base href, шрифты), пересборка @font-face |
| `test_eval_runner.py` | 251 | сам eval-раннер: загрузка cases, предикаты скоринга, вывод JSON/JUnit на мок-провайдере |
| `test_audit_fixes.py` | 76 | регрессии аудита безопасности: плохой пользовательский regex пропускается, а не роняет; заголовки правил в аналитике; файл ключа watch права 0600 и round-trip; навигационный guard блокирует loopback |

Что тестировать обязательно при правке: любое изменение формата кандидата/отчёта ломает контракты в `test_v2_pipeline_contracts.py`; изменение реестра или YAML ловит `test_styleguide_consistency.py`; правки watch DOM-слоя проверяются большим `test_watch.py`.

## Регрессия правил

`backend/app/regression_checks.py` 44 кейса вида «этот текст должен дать именно эти правила и не должен дать вот эти»:

```python
RegressionCase(
    name="em-dash ловится, дефисный перенос нет",
    text="Цена – 100 руб.\nЦена - 100 руб.",
    expect_rules=["RuStyleGuide.Dash_EmDash"],
    forbid_rules=[],
    forbid_texts=["Dash_NoSpace"],
)
```

Прогон `python -m app.regression_checks` (asyncio.run) гоняет все кейсы через полный `check_text`, то есть заодно через живой LanguageTool. Выход «Regression passed: 44 cases», при провале список и exit 1. Это же место, куда добавляется кейс на каждое новое правило (шаг 5 в [Правила гайда](guides-rules.md)).

## Eval против живой модели

`backend/eval/`: `cases.yaml` (версия 2) 20 эталонных документов с ожидаемыми находками по пяти способностям, и `run_eval.py` (483 строки) прогон через реальный конвейер с настроенной моделью. Пороги приёмки в том же YAML:

| Метрика | Порог |
|---|---|
| доля пройденных кейсов | ≥ 0.70 |
| recall по правилам | ≥ 0.80 |
| recall по блокам / span | ≥ 0.70 |
| recall по подсказкам | ≥ 0.60 |
| forbidden-нарушения | 0 |
| clean-кейсы с ложными находками | 0 |
| rule recall@k | ≥ 0.90 |
| finder / verifier rule recall | ≥ 0.80 |

Запуск `cd backend && python -m eval.run_eval` с заполненными `LLM_*`; форматы вывода JSON и JUnit. В CI нет: дёргает внешний API и деньги. Практический смысл: прогонять до и после смены версии промптов, модели или стадий конвейера, иначе «улучшение промпта» нечем измерить.

## Что не покрыто

Синхронный checker покрывается регрессией, но не unit-тами по движкам отдельно (vale postfilters, LT фильтры проверяются только сквозняком); краулер, репозиторий документов и OpenAPI-слой живут без отдельных тестов, их контракты косвенно проверяются smoke-шагом CI.

## Smoke в CI

`.github/workflows/ci.yml` (pull_request + push main, две jobs):

1. **lint-and-unit** python 3.12: `compileall`, `ruff check --select E9,F63,F7,F82` (детекторы сломанного кода, а не стиль), `pytest -q`.
2. **compose** полный стек на .env из примера: валидация трёх compose-файлов, build, `up -d`, ожидание `/api/health` до 180 с, гетты `/` и health, логин `admin/admin` в cookie-jar и проверка отсутствия 5xx на шести GET-маршрутах, ожидание готовности LanguageTool, `regression`, при провале дамп логов, всегда `down -v`.

## Дальше

- [Бэкенд](backend.md) что именно тестируется.
- [Правила гайда](guides-rules.md) как правильно добавлять кейсы.
- [Деплой](../ops/deploy.md) и [Дежурство](../ops/runbook.md) про рантайм-проверки.

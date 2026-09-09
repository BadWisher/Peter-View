# Правила гайда в коде

Правило стилистики существует в этом проекте в трёх воплощениях: YAML для Vale, запись реестра для движков и UI, и запись `rules.yaml` для LLM. Документ здесь объясняет, зачем три копии и как их менять синхронно. Что такое гайд глазами админа [Назначение гайда](../users/styleguide.md); как кандидаты от правил проходят верификатор [Конвейер](../arch/pipeline.md).

## Карта источников

| Артефакт | Кто ест | Формат |
|---|---|---|
| `backend/vale/styles/RuStyleGuide/*.yml` (48 файлов) | Vale CLI | стили `existence` / `substitution` / `consistency` с `raw`-regex |
| `backend/app/style_guide_registry.py` (56 правил + слой LT) | `checker.py` (обогащение issues), модалка правил UI, реестр для `effective_ids` | словари Python |
| `backend/styleguide/rules.yaml` (version 3, те же 56) | LLM-конвейер через RAG: тексты правил уходят в промпты | YAML |

Дублирование осознанное: Vale понимает только свои YAML, модели нужен человеческий текст правила с примерами, Python-слой держит метаданные (движок, автоматизация, приоритет, связи). Расхождение между реестром и `rules.yaml` ловит `test_styleguide_consistency.py`: сравнивает id, severity, поля. Поэтому порядок правки всегда один: реестр, потом перегенерация YAML, потом Vale-стиль.

## Реестр: поля записи

Каждый элемент `RULES` в `style_guide_registry.py`:

```python
{
  "id": "RuStyleGuide.Dash_EmDash",
  "section": "Пунктуация / Тире",
  "group": "Пунктуация",              # одна из 5 групп UI
  "name": "Длинное тире",
  "rule": "Не использовать em-dash...",
  "generalization": "...",            # как применять, для LLM
  "engine": "vale",                   # vale | python | manual
  "automation": "automatic",          # automatic | partial | manual
  "severity": "error",                # error | warning | suggestion
  "good_examples": ["..."], "bad_examples": ["..."],
  # служебные (для RAG и разрешения конфликтов):
  "categories": [...], "tasks": ["proofreading"], "scope": "all",
  "priority": 90,                     # error→90, warning→60, suggestion→40
  "machine_verifiable": True,         # находка не идёт к верификатору
  "relationships": {"supersedes": [...]}, "conflict_family": "...",
  "constraints": {"forbidden_chars": ["—"], "required_chars": ["–"]},
}
```

`constraints` не косметика: `llm/schemas.py` выбрасывает замечание модели, если её правка сама нарушает ограничение правила (например предложила em-dash там, где требуется en-dash, или внесла «ё» в слово из-под исключения).

Итоги по числам: 56 правил + запись `LanguageTool.ru` (орфографический слой не «правило», но лежит в реестре для единообразия UI) = 57. Из 56: vale 47, python 5, manual 4. Автоматически из vale-записей включаются 45 (`automation != manual`), `style_guide_rule_ids` отдаёт 52.

Группы для навигации в UI: Ключевые рекомендации (21), Общие принципы (12), Язык и грамматика (10), Пунктуация (8), Форматирование (5).

## Vale-стили

`.vale.ini` в `backend/vale` включает стиль `RuStyleGuide`. Файл стиля стандартный для Vale:

```yaml
extends: existence
message: "Убедитесь, что аббревиатура расшифрована при первом использовании."
level: suggestion
nonword: true
raw:
  - '\b[А-ЯЁ]{2,}\b'
exceptions: [IP, URL, HTTP, ...]
```

`vale_runner.py` запускает бинарь с `--output JSON` на временном файле, берёт сообщения и позиции. После Vale идут питоновские постфильтры (единицы Мбит/с у `Slash_Words`, исключения `её/ею/всё/все` у `LetterYo`, латинские аббревиатуры в кавычках у `Quotes_LatinInQuotes`), потому что regex Vale не различает контекст. Правило `Dash_EmDash` постфильтр расширяет до уровня предложения и подставляет замену en-dash.

Добавляя Vale-стиль, не забудьте запись в реестр с тем же хвостом id (`RuStyleGuide.<ИмяФайла>`) иначе: обогатитель `checker.py` не найдёт метаданные, UI покажет «голый» issue, `effective_ids` фильтрация в evidence отбросит находку как чужую.

## rules.yaml и генерация

`styleguide/rules.yaml` перегенерируется из реестра скриптом `styleguide/_generate.py` (одноразовая конвертация, запускается руками; поля берутся из реестра, `version` bumps при смене схемы). Файл примонтирован в контейнер read-only и подхватывается без пересборки образа: RAG-индекс сравнивает content hash и перестраивается.

В проде правила админ правит не в YAML, а через раздел гайдов (API `/api/styleguides`): встроенный bundle копируется в `data/styleguides/` сидингом `styleguide_store.seed_default()`, пользовательские гайды живут рядом. YAML-файл это поставка «из коробки».

## Тексты промптов

Промпты Jinja2 в `backend/app/llm/prompts/`, два каталога по версиям конвейера:

- `v1/`: `system_base`, `worker_1..worker_8` (восемь найденческих ролей: Грамотность, Форматирование, Стиль и тон, Соответствие гайду, Терминология, Критик, Согласованность, Лексикон) и `extractor` (извлечение гайда из DOCX).
- `v2/`: `system_base`, `language`, `guide_local`, `structure`, `terminology`, `consistency`, `verifier`.

`workers.py` выбирает каталог по env `PROMPT_VERSION`. В system-промпт инжектируются общие правила (`GENERAL_GROUP`), базовые формулировки и, если гайд содержит `extra_instruction`, её текст; кэш клиента включает версию промпта в namespace, поэтому правка шаблона сама по себе сбрасывает кэш ответов. Формат ответа строго JSON-схемой в шаблоне; менять поля можно только вместе с парсером в `workers.py` и дроп-правилами `schemas.py`.

Правила промптинга в проекте:

- Описания полей и примеров на русском, метазаметки для модели тоже (она читает ру-текст).
- Не вводить в промпты id правил: модель оперирует переданным фрагментом гайда, id проставляет код по контексту воркера.
- Правки текстов правил и промптов обязаны проходить `make regression` и, если задевали верификатор, прогон eval.

## Eval как приёмка правил

`backend/eval/cases.yaml` 20 эталонных текстов с ожидаемыми находками, `run_eval.py` прогоняет их через живой конвейер против настроенной модели и считает recall по правилам, блокам и подсказкам с порогами (например `min_rule_recall: 0.80`). Запуск: `cd backend && python -m eval.run_eval` (нужны `LLM_*` настройки; выход JSON/JUnit). Этот же runner покрыт тестами на mocked-провайдере (`test_eval_runner.py`), CI его не дёргает.

## Как добавить правило целиком

1. Придумать id и тексты: `rule`, `generalization`, хорошие/плохие примеры, severity, группу. Решить, чем оно исполняемо: regex → Vale-стиль, морфология → функция в `custom_checks.py`, смысл → только LLM (engine=manual не делают, оставляют vale/python с `automation: partial`).
2. Запись в `RULES` реестра со всеми метаданными (`machine_verifiable: True` только если находку можно проверить строкой, иначе верификатор будет резать живые замечания).
3. `python backend/styleguide/_generate.py` → diff `rules.yaml`.
4. Vale-файл или python-функция + подключение в `run_all_custom_checks`.
5. Регрессионный кейс в `regression_checks.py`: bad-текст обязан давать правило, good-текст не давать.
6. `make lint && make test && make regression`, при трогании LLM-слоя eval.

## Дальше

- [Тесты](tests.md) как именно консистентность проверяется.
- [Движки](../arch/engines.md) почему три копии и мост evidence.
- [HTTP API](api.md) маршруты гайдов и правил.

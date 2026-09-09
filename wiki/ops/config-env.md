# Переменные окружения

Источник конфигурации развёртывания файл `.env` рядом с `docker-compose.yml` (backend читает его через `env_file`). Часть переменных переопределяется настройками из UI (модель, эмбеддинги): там, где это так, помечено в таблице.

Приоритет: значения из блока `environment:` в compose-файле выше `.env`. Поэтому `PROOFREADER_DOCS`, `LANGUAGETOOL_URL`, `STYLEGUIDE_PATH`, `STYLEGUIDE_STORE_DIR` из `.env` backend не увидит они жёстко заданы в `docker-compose.yml` (ловушка, см. ниже).

## Основное

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `PROOFREADER_PORT` | 3080 | хостовый порт nginx (единственная публикация наружу) |
| `PROOFREADER_COOKIE_SECURE` | false | флаг `Secure` на сессионной cookie; ставьте true за HTTPS |
| `PROOFREADER_CORS_ORIGINS` | пусто | список origin через запятую для CORS (с credentials); пусто = same-origin |
| `PROOFREADER_DOCS` | false | Swagger: `/api/docs`, `/api/redoc`, `/api/openapi.json` |
| `JIRA_BASE_URL` | пусто | ссылка на Jira, показывается в payload сессии и в «Документах» |

**Ловушка `PROOFREADER_DOCS`.** В `docker-compose.yml` у backend в блоке `environment` жёстко стоит `PROOFREADER_DOCS=false`, и он перекрывает любое значение из `.env`. Включить Swagger через `.env` нельзя: правьте compose-файл или включайте через UI (раздел «Настройки» показывает ссылки на API). nginx при выключенном Swagger всё равно проксирует эти пути, просто приложение отвечает 404.

## Флаги разделов

Все выключены по умолчанию. Истинные значения: `1, true, yes, on, да` (регистр не важен).

| Переменная | Раздел | API-префикс |
|---|---|---|
| `FEATURE_DOCUMENTS` | Документы (репозиторий) | `/api/repo` |
| `FEATURE_API` | API-спецификации | `/api/api-spec*` |
| `FEATURE_WATCH` | Мониторинг страниц | `/api/watch` |
| `FEATURE_SCREENSHOTS` | Редактор скриншотов | `/api/screenshot-templates` |

Ядро (вычитка, гайды, история, аналитика) отключить нельзя.

## Безопасность и сеть

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `PROOFREADER_SSRF_ALLOW_PRIVATE` | true | разрешать пользовательским URL приватные сети (интранет). false на публичном хосте |
| `PROOFREADER_MAX_FETCH_BYTES` | 10485760 (10 MiB) | потолок размера скачанной страницы |
| `PROOFREADER_MAX_REDIRECTS` | 5 | сколько редиректов проходится при загрузке URL (каждый перепроверяется на SSRF) |
| `PROOFREADER_SECRET` | пусто (см. текст) | ключ обфускации хранимых паролей и снимков Мониторинга. Если пусто, сервис один раз генерирует случайный ключ и кладёт его в `data/watch.db.key` (0600) |

## Защита DOCX от zip-бомб

| Переменная | По умолчанию |
|---|---|
| `DOCX_MAX_UNCOMPRESSED_BYTES` | 314572800 (300 MiB) |
| `DOCX_MAX_COMPRESSION_RATIO` | 200 |
| `DOCX_MAX_ENTRIES` | 2000 |

## Модель и эмбеддинги (дублируются в UI)

Значения читаются из окружения как дефолт, но после первого сохранения через «Настройки» живут в `data/llm_settings.json` (права 0600) и имеют приоритет над `.env`. То есть UI перекрывает `.env`, а не наоборот.

| Переменная | Дефолт в коде | Дефолт в `.env.example` | UI-поле |
|---|---|---|---|
| `LLM_BASE_URL` | пусто (LLM выкл.) | пусто | Модель → Адрес API |
| `LLM_API_KEY` | пусто | пусто | API-ключ (секрет) |
| `LLM_MODEL` | пусто | пусто | Модель |
| `LLM_TEMPERATURE` | 0.0 | 0 | Температура |
| `LLM_CONCURRENCY` | 5 | 4 | Параллельность |
| `LLM_TIMEOUT` | 120.0 | 180 | Тайм-аут |
| `LLM_JSON_MODE` | true | true | JSON-режим |
| `LLM_REASONING_EFFORT` | пусто | low | Усилие рассуждения |
| `EMBEDDING_BASE_URL` / `_API_KEY` / `_MODEL` | пусто | пусто | Эмбеддинги |

**Расхождение дефолтов.** `LLM_CONCURRENCY` и `LLM_TIMEOUT` в коде (5 и 120) отличаются от `.env.example` (4 и 180). Реальное значение то, что в файле настроек; если `.env` задан, он задаёт стартовый дефолт. Держите `.env` и ожидания команды согласованными.

Прочие LLM-переменные (только из окружения, в UI нет): `LLM_JOB_TIMEOUT` (900, потолок жизни задачи), `LLM_STREAM_BLOCK_CAP` (20000, знаков на блок стрима).

## Пайплайн и промпты

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `PIPELINE_VERSION` | v2 | v1 или v2 конвейера LLM (v1 оставлен для откатов) |
| `PIPELINE_SHADOW` | false | параллельно гонять v1 и v2 для сравнения метрик |
| `PIPELINE_V2_STAGES` | evidence,language,guide,structure,terminology,consistency,lexicon,verifier | включённые стадии v2 (списком через запятую) |
| `PIPELINE_V2_PASS_TIMEOUT` | 360 | тайм-аут одного прохода воркера, секунд |
| `PIPELINE_V2_PASS_RETRIES` | 2 | повторы прохода при тайм-ауте/сетевой ошибке |
| `RAG_CONFIG_VERSION` | v1 в коде, v2 в `.env.example` | версия кэша/схемы RAG в клиенте эмбеддингов |
| `PROMPT_VERSION` | v1 | набор Jinja2-промптов для воркеров |
| `EMBED_TIMEOUT` | 20 | тайм-аут запроса эмбеддингов |
| `EMBED_BATCH_SIZE` | 90 | размер батча эмбеддингов |
| `STYLEGUIDE_EXTRACT_TIMEOUT` | 900 | потолок извлечения гайда из документа |
| `STYLEGUIDE_EXTRACT_CONCURRENCY` | 3 | параллельность чанков при извлечении |

## Мониторинг страниц (watch)

| Переменная | По умолчанию |
|---|---|
| `WATCH_STORE_PATH` | путь к `data/watch.db` (обычно не трогают) |
| `WATCH_SNAPSHOT_KEEP` | 14 (снимков на страницу) |
| `WATCH_TEXT_CAP` | 200000 (знаков текста на снимок) |
| `WATCH_DOM_CAP` | 1500000 (байт DOM на снимок) |
| `PROOFREADER_WATCH_RENDER_TIMEOUT` | 25 |
| `PROOFREADER_WATCH_RENDER_SETTLE_MS` | 1200 (ждать устоятия страницы перед рендером) |
| `PROOFREADER_WATCH_HOUR` | 4 (час фонового обхода) |
| `PROOFREADER_WATCH_MIN_CHARS` | 24 (ниже страница считается пустой) |
| `WATCH_USER_AGENT` | `Proofreader/1.0` |

## Репозиторий документов

| Переменная | По умолчанию |
|---|---|
| `REPO_STORE_DIR` | путь к `data/repo` |
| `REPO_MAX_FILE_BYTES` | 26214400 (25 MiB) |
| `REPO_ARCHIVE_AFTER_DAYS` | 90 |
| `REPO_JIRA_PROJECT` | пусто (префикс задач Jira) |

## Прочее

| Переменная | По умолчанию |
|---|---|
| `USER_REGEX_TIMEOUT_MS` | 200 (лимит на пользовательскую регулярку, мс на строку) |
| `BACKUP_DIR` | /app/backups |
| `BACKUP_KEEP` | 7 (автоснапшотов хранить) |
| `GHCR_REPOSITORY` | требуется только для `docker-compose.prod.yml` |
| `IMAGE_SHA` | требуется только для `docker-compose.prod.yml` |
| `CORP_PROXY_UPSTREAM` | 127.0.0.1:3128 (для corp-proxy overlay) |
| `CORP_PROXY_BRIDGE_PORT` | 3128 |
| `CORP_PROXY_BRIDGE_BIND` | 172.17.0.1 |

## Переменные, заданные в compose, а не в `.env`

Эти четыре значения зашиты в `environment:` у backend в `docker-compose.yml`, в `.env` их искать бессмысленно (перекроются): `LANGUAGETOOL_URL` (`http://languagetool:8010/v2/check`), `STYLEGUIDE_PATH` (`/app/styleguide/rules.yaml`), `STYLEGUIDE_STORE_DIR` (`/app/data/styleguides`), `PROOFREADER_DOCS` (false).

## Дальше

- [Стек и его детали](stack.md) про compose-файлы и образы.
- [TLS и обратный прокси](tls-proxy.md) куда вписывается `PROOFREADER_COOKIE_SECURE`.
- [Бэкапы](backup.md) про `BACKUP_*`.

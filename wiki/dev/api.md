# HTTP API

Полный контракт эндпоинтов. Сервис описывает сам себя через OpenAPI: при `PROOFREADER_DOCS=true` доступны `/api/openapi.json`, Swagger `/api/docs` и ReDoc `/api/redoc` (в compose-файле флаг зашит false, см. [Переменные](../ops/config-env.md)). Здесь то же самое, но человеческим языком и с поведенческими деталями, которые схема не покажет.

## Соглашения

- Префикс `/api/`, всё JSON, кроме multipart-входов и бинарных выходов (xlsx, PNG, YAML, HTML-копия).
- Авторизация сессионная cookie `proofreader_session` (HttpOnly, SameSite=Lax). Нет cookie или сессия истекла 401. Роль `admin` на админ-ручках 403. Выключенный раздел 404 (`feature_gate`).
- CSRF: токен не нужен, сервер сверяет Origin/Referer с хостом запроса для не-GET (403 «Перекрёстный запрос отклонён»).
- Ошибки всегда `{"detail": "сообщение по-русски"}`; код несёт смысл (400 вход, 401 вход не авторизован, 403 роль, 404 нет раздела/сущности, 409 конфликт, 429 rate limit).
- Тело запроса к `/api/` ограничено 50 МиБ на nginx; файлы репозитория отдельно 25 МиБ.
- Долгие проверки асинхронные: POST создаёт job, статус и результат читаются отдельно.

Разделы с флагом: `/api/repo*` (`FEATURE_DOCUMENTS`), `/api/watch*` (`FEATURE_WATCH`), `/api/api-spec*` и `/api/api-spec-documents` (`FEATURE_API`), `/api/screenshot-templates*` (`FEATURE_SCREENSHOTS`).

## Служебное и авторизация

| Метод | Путь | Роль | Назначение |
|---|---|---|---|
| GET | `/api` | публ. | имя и версия сервиса, ссылки на доки если включены |
| GET | `/api/health` | публ. | `{"status":"ok","version":"0.1.0"}` |
| GET | `/api/health/full` | admin | диск, токены, LLM/эмбеддинги, репозиторий, бэкап, `audit[]` |
| GET | `/api/config` | публ. | `version`, `features`, `oidc`, `docs` для старта SPA |
| POST | `/api/auth/login` | публ. | `{username,password}` → профиль, ставит cookie |
| GET | `/api/auth/me` | user | `{username,role,source,jira_base_url}` |
| POST | `/api/auth/logout` | user | рвёт сессию, снимает cookie |
| POST | `/api/auth/change-password` | user | `{current_password,new_password}` (мин. 8); для OIDC-учёток 400 |
| GET | `/api/auth/oidc/start` | публ. | 302 на провайдера; 404 если OIDC не настроен |
| GET | `/api/auth/oidc/callback` | публ. | `?code&state`, 302 на `/#/check` с cookie |

Логин: 5 попыток на `ip:username` и на `ip` за 300 с, превышение 429. Локальный вход для пользователя `source:"oidc"` отвергается.

## Пользователи (admin)

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/users` | `{users:[{username,role,source}]}` |
| POST | `/api/users` | `{username,password,role}`; пустой пароль генерируется `secrets.token_urlsafe(9)` и возвращается один раз; 409 дубликат |
| PATCH | `/api/users/{username}` | только смена роли; нельзя понизить последнего админа |
| DELETE | `/api/users/{username}` | нельзя удалить себя и последнего админа; рвёт сессии |

## Вычитка: синхронный движок

Быстрые проверки без модели, все `require_user`. Ответ содержит `issues[]`, `summary`, `source`.

| Метод | Путь | Вход | Примечание |
|---|---|---|---|
| POST | `/api/check` | multipart `file` (.docx/.txt/.html/.md, ≤50 МиБ), опц. `user_rules` (JSON-строка) | чанки по 500 строк; `{source,text_length,pages_checked,issues,summary}` |
| POST | `/api/check-text` | form `text` | тот же ответ |
| POST | `/api/check-url` | form `url` | **SSE**: `progress` на каждую страницу краулинга, финальный `done`, `error` если ничего не сняли; 3 страницы одновременно, 300 с на страницу |
| POST | `/api/report` | file **или** text | сразу xlsx-байты (со своим `rules.json`, без `user_rules`) |
| POST | `/api/report-issues` | `{issues:[...],source}` | xlsx из готовых замечаний без перепроверки |

## Вычитка: LLM-задачи

Долгий конвейер с моделью. `POST /api/jobs` multipart: `text` **или** `file` **или** `url`, `styleguide_id`, флаги `check_language`/`check_styleguide`/`check_consistency` (≥1 обязателен), `prompt` (≤4000 симв.). Ответ мгновенно `{"job_id"}`.

| Метод | Путь | Ответ |
|---|---|---|
| GET | `/api/jobs/{id}` | `{job_id,status,stage,error}` (status: pending/running/done/error; только свой job) |
| GET | `/api/jobs/{id}/stream` | **SSE**, события `start/delta/end/finished`, ping 15 с |
| GET | `/api/jobs/{id}/report` | полный отчёт; 409 если не готов, 500 при ошибке |

Таймаут задачи 900 с, TTL результата в памяти и базе 1 час.

### Форма issues и summary

`summary` из синхронного `/api/check*`: `{total, errors, warnings, suggestions}`. Отчёт `/api/jobs/{id}/report` несёт `issues[]`, `blocks[]`, `document`, `styleguide`, `pages_checked`, `partial`, `meta` (`pipeline_version`, `passes_total`, `token_usage`, при теневом режиме `shadow_comparison`), плюс счётчики `blocker/suggestion/minor` в `summary`.

Замечание LLM после приведения к UI (`to_ui_issue`): `{line, text, severity, message, replacement, rule, source:"llm", rule_group, page_url}`; в `message` к описанию через пустую строку дописано «Обоснование: ...». `severity` для клиента всегда одна из `error|warning|suggestion` (внутренние модели `blocker|suggestion|minor` отображаются). Замечание детерминированного движка: `{line, column, text, message, severity, rule|registry_id, source ("style-guide"|"spelling"|"custom"), guide_section, rule_name, automation, rule_group}`, у части есть `replacement`.

Frontend `normalizedIssues()` намеренно терпит алиасы (`line|line_number|block_index`, `fragment|match|span_text`, `recommendation|replacement|suggestion`), чтобы старые интеграции не падали.

Формат xlsx (`report.py`), лист «Отчет»: строка заголовка `# | [Страница] | Строка | Фрагмент | Тип | Серьезность | Описание | Рекомендация` (колонка «Страница» появляется, если у замечаний есть `page_url`), строки подцвечены по severity, значения-формулы экранированы ведущим `'`. Лист «Информация» с метаданными источника.

## История и аналитика (user)

| Метод | Путь | Что возвращает |
|---|---|---|
| GET | `/api/checks/history?limit&offset` | страницы истории (`limit` 1..50, по умолчанию 10; хранится 50 последних на пользователя) |
| GET | `/api/checks/history/{id}` | полный сохранённый отчёт (только свой) |
| GET | `/api/checks/top-rules` | топ-15 нарушенных правил текущего пользователя с названиями из всех гайдов |
| GET | `/api/checks/insights` | сводка токенов (всего/сегодня) + правила по пользователям |

## Гайды и правила

| Метод | Путь | Роль | Действие |
|---|---|---|---|
| GET | `/api/styleguides` | user | список мета + выбранный |
| GET | `/api/styleguides/current` | user | активный гайд пользователя |
| GET | `/api/styleguides/{id}` | user | полные rules + lexicon |
| POST | `/api/styleguides/{id}/select` | user | запомнить выбор в `user_prefs.json` |
| POST | `/api/styleguides` | admin | создать из `{name, rules, lexicon}` |
| PUT | `/api/styleguides/{id}` | admin | обновить |
| DELETE | `/api/styleguides/{id}` | admin | удалить (встроенный 403) |
| GET | `/api/styleguides/{id}/index-status` | user | режим RAG: hybrid / lexical_only / fallback |
| POST | `/api/styleguides/extract` | admin | multipart DOCX → `{job_id}` извлечение правил |
| GET | `/api/styleguides/extract/{job_id}` | admin | прогресс/результат извлечения |

| Метод | Путь | Роль | Действие |
|---|---|---|---|
| GET | `/api/rules` | user | свои regex-правила из `rules.json` |
| GET | `/api/rules/builtin` | user | весь реестр встроенных правил (57 записей) |
| POST | `/api/rules` | admin | regex-правило (проверка компиляции, severity ∈ error/warning/suggestion) |
| DELETE | `/api/rules/{rule_id}` | admin | удалить своё правило |

## Настройки (admin)

GET `PUT /api/settings` 11 полей модели и эмбеддингов; секреты в GET не отдаются, вместо них `llm_api_key_set`/`embedding_api_key_set`; пустой секрет при PUT не затирает прежний. POST `/api/settings/test` healthcheck LLM и эмбеддингов, по 30 с на каждый.

## Документы (`FEATURE_DOCUMENTS`)

Репозиторий файлов, `require_user`, загрузка multipart.

- `GET /api/repo/folders?parent=`, `/api/repo/tree`, `/api/repo/archived`, `/api/repo/search?q=`, `/api/repo/usage`.
- `POST /api/repo/folders`, `PATCH|DELETE /api/repo/folders/{id}` (нельзя удалить непустую, перемещение без циклов).
- `POST /api/repo/documents` (multipart `file,folder_id,name,jira,note`, ≤25 МиБ), `GET /api/repo/documents/{id}` (таймлайн версий), `PATCH` (переименование/перемещение), `DELETE`.
- `POST /api/repo/documents/{id}/versions` (`kind` upload|review), `GET .../versions/{n}` (скачивание, имя файла в RFC 5987), `POST .../archive|unarchive`.

## Спецификации API (`FEATURE_API`)

Парные RU/EN OpenAPI из документов репозитория.

- CRUD `GET|POST /api/api-specs`, `GET /api/api-spec-documents`, `PATCH|DELETE /api/api-specs/{id}`.
- `GET .../segments?page&size(1..250, по умолч. 25)&q` пары RU/EN по `path_str`; `GET .../consistency?lang=ru|en`; `GET .../diff`.
- `POST .../translate`, `POST .../ai-review` → `{job_id}` (отчёт через `/api/jobs/{id}`); `POST .../download` `{target:"ru"|"en",edits:{path_str:text}}` → пропатченный YAML.

## Мониторинг (`FEATURE_WATCH`)

- Группы: `GET|POST /api/watch/groups`, `GET|PATCH|DELETE /api/watch/groups/{id}` (GET включает `pages[]`).
- Страницы: `POST /api/watch/groups/{id}/pages`, `PATCH|DELETE /api/watch/pages/{id}`.
- Запуск: `POST /api/watch/groups/{id}/run`, `POST /api/watch/pages/{id}/run` → `{status:"started"|"running"}`.
- Данные: `GET /api/watch/pages/{id}/diff` (хунки + UI-события + метки), `/history`, `POST /{id}/seen` (снять бейдж).
- Артефакты: `GET /api/watch/pages/{id}/copy?v=new|old` (самодостаточный HTML, `text/html`, отдельный CSP), `GET .../shot?v=` (PNG через chromium, 503 если недоступен).

Пароли порталов в группах write-only (`has_password`), шифруются под `PROOFREADER_SECRET`.

## Скриншоты (`FEATURE_SCREENSHOTS`)

`GET|POST /api/screenshot-templates`, `DELETE /api/screenshot-templates/{id}`. Запись `{id,name,width}`, ширина 50..4000, список общий. Генерации картинок на сервере здесь нет, это пресеты ширины для клиентского редактора.

## Дальше

- [Бэкенд](backend.md) какие модули за какими роутами стоят.
- [Модель данных](../arch/data-model.md) где что хранится.
- [Конвейер](../arch/pipeline.md) как устроен ответ `/report`.

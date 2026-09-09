# Бэкенд: код FastAPI

Серверное приложение живёт в `backend/app`, один процесс uvicorn, весь асинхронный код на asyncio. Здесь конвенции кода и типовые задачи разработчика: добавить маршрут, добавить проверку, добавить воркер. За тем, как части стыкуются между собой, [Архитектура](../arch/overview.md).

## Сборка приложения

`app/main.py` (164 строки) создаёт `FastAPI(title="Peter View API", version="0.1.0")` и навешивает по порядку три middleware:

1. **CORSMiddleware** origins из `PROOFREADER_CORS_ORIGINS` (пусто = только same-origin), `allow_credentials=True`.
2. **csrf_origin_guard** для всех не-GET сверяет хост из Origin/Referer с хостом запроса; чужой 403 «Перекрёстный запрос отклонён». Отдельных CSRF-токенов нет, фронт ходит same-origin через nginx.
3. **feature_gate** пути `/api/watch*`, `/api/repo*`, `/api/api-spec*`, `/api/screenshot-templates*` отдают 404, когда соответствующий раздел выключен флагом `FEATURE_*`.

Дальше `include_router` для 15 роутеров, и два import-time побочника: `auth.seed_default_admin()` и `styleguide_store.seed_default()` (заводят `admin/admin` при пустой базе и встроенный гайд при пустом хранилище). Startup-хендлеры (`on_event("startup")`) запускают три фоновых цикла из `routers/background.py`: авто-архив репозитория, ежедневный бэкап, ежедневный обход мониторинга. Shutdown-хендлеров нет, при рестарте незавершённые задачи помечаются ошибкой «Прервано рестартом сервера» на следующем старте.

Swagger (`/api/docs`, `/api/redoc`, `/api/openapi.json`) открыт только при `PROOFREADER_DOCS=true`. В `docker-compose.yml` этот флаг зашит в `environment:` как false и перекрывает `.env`.

## Роутеры

HTTP-слой в `app/routers/`, по файлу на домен (строки: `auth.py` 146, `checks.py` 191, `jobs.py` 185, `repo.py` 278, `specs.py` 257, `styleguides.py` 192, `watch.py` 235, остальные меньше). Всего 89 маршрутов, таблица контрактов [HTTP API](api.md).

Конвенции слоя:

- Авторизация через FastAPI-зависимости из `auth.py`: `Depends(require_user)` для «нужен вход», `Depends(require_admin)` для админских ручек, фабрика `require_feature("watch")` для разделов с флагом.
- Лимиты входа задаются локально: `infra.py` константа `MAX_UPLOAD_BYTES` (50 МиБ), файл больше 400 с текстом про максимум; текст и поле `prompt` тоже режутся на роутере, до тяжёлой работы.
- Формы multipart/`Form(...)` там, где отправляет браузер, JSON-тело там, где программируемый клиент.
- Долгие задачи роутер не ждёт: `POST /api/jobs` возвращает `{"job_id"}` и уходит, работа идёт в `asyncio.create_task` через очередь `llm/jobs.py`. Стрим прогресса отдельным SSE-маршрутом.
- Ошибки всегда `HTTPException(status, "человеческое сообщение по-русски")` фронт показывает `detail` как есть.
- Теги OpenAPI проставляет `custom_openapi()` из `main.py`: префикс пути → тег из `_PATH_TAGS` (`openapi_meta.py`), плюс схема `CookieAuth` на `proofreader_session`. Публичные маршруты (`/api`, `/api/health`, логин, доки) помечены без security.

Чтобы добавить маршрут: создаёте функцию в нужном роутере (или новый `APIRouter` и регистрируете в `main.py`), вешаете зависимости, возвращаете dict. Больше никуда вписывать не нужно, автотегирование и security подхватят путь по префиксу.

## Аутентификация и роли

`auth.py` (157 строк). Роли ровно две, `ROLES = ("admin", "editor")`, роль даёт: у админа пользователи, настройки, создание гайдов и правил; у редактора всё остальное. Пароли bcrypt в `users.json`, `MIN_PASSWORD = 8`, сложность не проверяется. Учётки из OIDC помечаются `source:"oidc"`, смена пароля для них запрещена на уровне роутера.

Сессии живут в процессной памяти (`SESSIONS: dict`), cookie `proofreader_session`, токен `secrets.token_urlsafe(32)`, TTL 12 часов со скользящим продлением на каждом `current_user`. `PROOFREADER_COOKIE_SECURE=true` добавляет флагу `Secure`. Рестарт сервиса разлогинивает всех, это осознанное решение, детали [Проектные решения](../arch/decisions.md).

Rate limit логина (`routers/session.py`): 5 попыток на окно 300 секунд по ключам `ip:username` и отдельно `ip:*`, смена пароля так же. Клиентский IP берётся из `X-Real-IP`, иначе первый адрес `X-Forwarded-For`.

`oidc.py` (110 строк) классический Authorization Code: discovery по `OIDC_ISSUER/.well-known/openid-configuration` (кэш), state+nonce в модульном словаре `_pending` на 600 секунд, обмен кода на токены (`client_secret_post`), username из `preferred_username|email|sub`, роль `admin` если группы пользователя пересекаются с `OIDC_ADMIN_GROUPS`. Обратный вызов мигрирует локальную учётку на OIDC по `oidc_sub` и очищает пароль.

## Флаги разделов

`features.py` (35 строк): `OPTIONAL = ("documents", "api", "watch", "screenshots")`, каждый читается из `FEATURE_*`; считаются истиной `1|true|yes|on|да`. Разделы «Вычитка», «Гайды», «История», «Аналитика» всегда включены, флагов нет. Состояние наружу отдаёт `GET /api/config` через `features.snapshot()`, фронт по нему скрывает навигацию, middleware и зависимости держат серверную часть. Фоновые циклы (`repo auto-archive`, ежедневный обход watch) при выключенном флаге себя не поднимают.

## Детерминированный checker

`checker.py` (166 строк) фасад `check_text(text, user_rules, include_spelling=True)`:

- Vale, LanguageTool и custom-проверки стартуют параллельно (`asyncio.gather(return_exceptions=True)`; vale и lt как задачи event loop, python-движок в потоке через default executor). Упавший движок не роняет проверку, его результат пустой.
- Каждый issue обогащается полями реестра (`registry_id, guide_section, rule_name, automation, rule_group`) и источником: vale+python `"style-guide"`, LT `"spelling"` с `registry_id="LanguageTool.ru"`, пользовательские regex `"custom"`.
- Дедуп в два хода: сначала орфографическое замечание с тем же `(line, column, fragment.lower())`, что у стилистического, выбрасывается (грамматист не должен плодить дубли к термину), затем точный `(line, column, text, rule)` по всем движкам.
- Пользовательские regex исполняются модулем `regex` (не stdlib `re`) с таймаутом `USER_REGEX_TIMEOUT_MS` по умолчанию 200 мс на `finditer` и длиной паттерна не больше 500; зависший паттерн пропускается, а не вешает проверку.

Движки под фасадом:

| Модуль | Строк | Как работает |
|---|---|---|
| `vale_runner.py` | 161 | subprocess `vale --output JSON` с конфигом `backend/vale/.vale.ini`, включены 45 id из реестра (engine=vale, automation != manual); постфильтры: единицы вида Мбит/с у `Slash_Words`, «отклик» у `UITerms_Click`, исключения её/ею/всё/все у `LetterYo`, латинские аббревиатуры в кавычках; `Dash_EmDash` переписывается на уровень предложения с заменой на en-dash |
| `lt_client.py` | 221 | по одному запросу к LanguageTool на строку, `asyncio.Semaphore(8)`, httpx 30 с; если хост лежит целиком, предупреждение в лог и пустой список; категория → severity: опечатки/орфография error, грамматика/пунктуация warning, стиль/типографика suggestion |
| `custom_checks.py` | 394 | pymorphy3 + razdel, пять запусковых функций: `check_anthropomorphism`, `check_sentence_length` (>25 слов), `check_formal_you`, `check_adj_noun_agreement`, `check_subject_verb_agreement`; `check_passive_voice` в файле есть, но не вызывается (правило manual в реестре) |

Извлечение текста `extractors.py` (278 строк) знает docx (python-docx с обходом XML: таблицы, вложенные списки), html (BeautifulSoup+lxml, вырезает `nav/footer/header/aside`, скрытые узлы, class/id с nav-паттернами), md и txt. DOCX проходит zip-bomb guard: до 300 МиБ разархивированного, ratio до 200, до 2000 записей. Разбор в блоки для LLM-конвейера отдельный (`llm/documents.py`, см. [Конвейер](../arch/pipeline.md)), здесь плоский разбор в строки для движков.

Краулер `crawler.py` (191 строка) для `/api/check-url`: BFS по домену, `MAX_PAGES=200`, `MAX_CONCURRENT=5`, страница 20 с, robots.txt с UA `Proofreader/1.0`, ~40 бинарных расширений пропускаются, URL нормализуются (срезается query/fragment), стоп после 10 пустых батчей подряд. Каждый fetch идёт через `net_guard.safe_get`.

`net_guard.py` (157 строк) обход SSRF: только http/https, резолвит хост и проверяет каждый адрес (loopback, link-local включая metadata 169.254/fe80::, multicast, reserved отсекаются; приватные сети по умолчанию разрешены `PROOFREADER_SSRF_ALLOW_PRIVATE=true` для интранета). Редиректы шагаются вручную (`follow_redirects=False`) с перепроверкой каждого хопа, POST на 301/302/303 понижается до GET, тело читается потоково с лимитом `PROOFREADER_MAX_FETCH_BYTES` (10 МиБ).

## Реестр правил

`style_guide_registry.py` (817 строк) 56 встроенных правил `RULES` + запись слоя орфографии `LanguageTool.ru` (итого 57), сгруппированные по полям: `id, section, group, name, rule, engine (vale|python|manual), automation (automatic|partial|manual), severity, generalization, good_examples, bad_examples` плюс служебные `categories, tasks, scope, priority (error→90, warning→60, suggestion→40), machine_verifiable, relationships, conflict_family`, у некоторых `constraints` (например forbidden_chars `—`, required `–`, forbidden_introduced `ё`). Хелперы: `get_rule`, `enabled_vale_rule_ids` (45), `style_guide_rule_ids` (52), `get_registry(include_spelling)`. Держать реестр в ладу с `styleguide/rules.yaml` заставляет тест, см. [Правила гайда](guides-rules.md).

## Пакет llm/

Самая большая часть (25 модулей), её устройство по страницам [Конвейер](../arch/pipeline.md), [Движки](../arch/engines.md), [Клиент модели](../arch/model-client.md), [Подсистемы](../arch/subsystems.md). Здесь ownership по модулям, чтобы искать код по задаче:

- `documents.py` (717) вход → `Document` со списком `Block {index, raw, plain, metadata}`; типы блоков, форматирование, лимиты (16000 символов структурированной выдержки, 2000 на блок).
- `chunking.py` (167) 8 блоков в чанке, overlap 2, атомарные «введение + список»; `compress()` каркас из первых 12 слов блока.
- `pipeline.py` (471) планировщик версий: читает `PIPELINE_VERSION` (default v2) и `PIPELINE_SHADOW`, здесь же v1 (8 воркеров + критик) ради откатов и теневого сравнения `(block_index, rule_id, replacement)`.
- `pipeline_v2.py` (698) стадии v2 из `PIPELINE_V2_STAGES`: evidence → retrieval → finders (language/structure/guide_local по чанкам, terminology/consistency по документу) → verifier батчами по 12 (`VERIFY_BATCH`) → разрешение конфликтов (`relationships.supersedes/specializes`, `conflict_family`, `rule_precedence_key`) → сборка отчёта. Каждый проход с retry: `PASS_TIMEOUT=360`, `PASS_RETRIES=2`, backoff `min(10, 2^n)`.
- `workers.py` (457) вызовы модели по Jinja2: `prompts/v1/` (system_base, worker_1..worker_8, extractor) и `prompts/v2/` (system_base, language, guide_local, structure, consistency, terminology, verifier). Смена `PROMPT_VERSION` переключает шаблонный каталог.
- `client.py` (461) OpenAI-совместимый клиент: семафор `llm_concurrency`, `MAX_RETRIES=5`, backoff на rate limit `min(30, 3*2^n)`, на лимит токенов `min(45, 5*2^n)`; кэш ответов: память 1024 + SQLite `stats.db:llm_cache`, ключ sha256(model, namespace, system, user), namespace склеен из версий пайплайна/промптов/RAG, поэтому смена `RAG_CONFIG_VERSION` инвалидирует кэш; фолбэк json_mode и reasoning_effort при отказе сервера запоминается в `_unsupported`; стриминг дельт до первой `{`.
- `evidence.py` (105) мост детерминированных движков в схему кандидатов LLM: `collect_engine_evidence` (checker на блоках, фильтр по `guide.effective_ids`), `collect_lexicon_evidence` (запрещённые термины по границе слова).
- `jobs.py` (278) очередь и стрим: SQLite `jobs.db` (таблица `jobs`: id, source, status, stage, report, error, created_at), TTL час, `JOB_TIMEOUT_SECONDS=900`, потолок блока стрима 20 000 символов с подрезкой начала; события SSE `start/delta/end/finished`.
- `schemas.py` (191) нормализация кандидата и анти-галлюцинационные дропы (`span_text` не подстрока блока, неизвестный `rule_id`, suggestion == оригинал, нарушение `constraints` правила); severity модели `blocker|suggestion|minor` → UI `error|warning|suggestion`.
- `rag.py` (451) гибрид-поиск правил по гайду: 3 эмбеддинга на правило (identity/policy/examples), скор `0.55*lexical + 0.45*semantic`, бусты по метаданным, три яруса отката hybrid → lexical_only → all_rules; индекс в памяти, пересборка по content hash.
- `settings.py` (153) 11 настраиваемых полей (LLM/эмбеддинги/тайминги), JSON `llm_settings.json` поверх env, секреты маскируются флагами `*_set`, слушатели (`client`, `rag`) сбрасывают кэш на изменение.
- `stats.py` (403) SQLite `stats.db`: `token_usage` (атрибуция через contextvars по user/job/worker), `rule_hits`, `check_history` (50 записей на пользователя), `doc_views`, `llm_cache`.
- `repo_store.py` (532) файловая библиотека документов `repo/` (folders.json, docs/*.json, blobs, zip-архив), лимит 25 МиБ, авто-архив через 90 дней.
- `api_specs.py` + `openapi_fields.py` + `api_review.py` (807 суммарно) раздел «Вычитка API»: парные RU/EN YAML (ruamel round-trip, `path_str` как ключ поля), consistency по names/texts, review-aware diff, батчи translate/review по 20, точечная перезапись YAML с сохранением CRLF/блок-скаляров.
- `watch_store.py` (585) SQLite `watch.db` (groups, pages, snapshots, meta, fonts), пароли порталов XOR+HMAC под `PROOFREADER_SECRET`, 14 снимков на страницу; `watch_run.py` (563) httpx + всегда chromium-перерендер, дубли-детект по content/struct hash; `watch_dom.py` (669) structural diff и деперсонализация (телефоны, почты, карты, СНИЛС, ИНН), генерация HTML-копии; `watch_render.py` (154) ленивый общий chromium, навигационный guard поверх `net_guard`.
- `extractor.py` (260) + `extract_jobs.py` (270) извлечение гайда из DOCX: куски по 3500 символов, промпт-экстрактор, merge по (title, rule), job-таблица `extract_jobs.db`.
- `styleguide_store.py` (447) хранит гайды админа и пользователя в `data/styleguides/`, считает `effective_ids` и разрешает конфликты поверх встроенного реестра.
- `shot_templates.py` (105) пресеты ширины скриншотов `screenshot_templates.json`.

## Данные

Всё состояние в томе `backend-data:/app/data`: `users.json`, `rules.json`, `user_prefs.json`, `llm_settings.json`, `audit.jsonl`, `screenshot_templates.json`, `jobs.db`, `stats.db`, `watch.db`, `extract_jobs.db`, `styleguides/`, `repo/`, `uploads/`, файл-ключ `watch.db.key` (или `PROOFREADER_SECRET` из env). Схема, размеры и владение [Модель данных](../arch/data-model.md).

## Регрессия и аудит как CLI

```bash
docker compose exec backend python -m app.regression_checks   # 44 кейса, exit 1 при провале
docker compose exec backend python -m app.site_audit https://example.com --max-pages 40
```

Первая команда часть CI (`make regression`), вторая разовый прогон по живому сайту с JSON-сводкой по правилам.

## Дальше

- [Фронтенд](frontend.md) как этот API потребляет SPA.
- [Правила гайда](guides-rules.md) где править тексты правил и промптов.
- [Тесты](tests.md) защитная сетка для всего перечисленного.
- [Движки](../arch/engines.md) и [Конвейер](../arch/pipeline.md) глубже про то же.

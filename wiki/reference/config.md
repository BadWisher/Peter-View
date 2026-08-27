# Переменные .env

Файл лежит рядом с `docker-compose.yml`. Если `.env` ещё нет, `./deploy.sh` копирует `.env.example`. Пустые `LLM_*` значат: нейросеть не вызывать.

Значения, которые администратор сохранил в «Настройках», лежат в томе и перекрывают `LLM_*` и `EMBEDDING_*` из файла.

## Порт и cookie

| Переменная | По умолчанию | Значение |
|---|---|---|
| `PROOFREADER_PORT` | `3080` | Порт nginx на хосте |
| `PROOFREADER_COOKIE_SECURE` | `false` | `true` за HTTPS |
| `PROOFREADER_CORS_ORIGINS` | пусто | Дополнительные Origin |
| `PROOFREADER_DOCS` | `false` | Swagger UI |

## Разделы

| Переменная | По умолчанию | Раздел |
|---|---|---|
| `FEATURE_DOCUMENTS` | `false` | Документы |
| `FEATURE_API` | `false` | OpenAPI |
| `FEATURE_WATCH` | `false` | Наблюдение |
| `FEATURE_SCREENSHOTS` | `false` | Скриншоты |

Вычитка, Style Guide, история и аналитика флагами не выключаются.

## Сеть

| Переменная | По умолчанию | Значение |
|---|---|---|
| `PROOFREADER_SSRF_ALLOW_PRIVATE` | `true` | Fetch URL во внутреннюю сеть. На публичном хосте `false` |
| `PROOFREADER_MAX_FETCH_BYTES` | 10 МиБ | Потолок скачивания страницы |
| `PROOFREADER_CORP_PROXY` | `false` | Подключает `docker-compose.corp-proxy.yml` |

## Модель

| Переменная | Значение |
|---|---|
| `LLM_BASE_URL` | Корень OpenAI-совместимого API. Пусто: полной проверки нет |
| `LLM_API_KEY` | Ключ |
| `LLM_MODEL` | Имя модели |
| `LLM_TEMPERATURE` | По умолчанию `0` |
| `LLM_CONCURRENCY` | Параллельные запросы, в примере `4` |
| `LLM_TIMEOUT` | Секунды |
| `LLM_JSON_MODE` | `true` / `false` |
| `LLM_REASONING_EFFORT` | `low`, `medium` или `high` |
| `EMBEDDING_BASE_URL` | Корень эмбеддингов. Пусто: поиск по гайду без векторов |
| `EMBEDDING_API_KEY` | Ключ эмбеддингов |
| `EMBEDDING_MODEL` | Имя модели эмбеддингов |

Администратор может задать те же поля в разделе «Настройки». Сохранённые там значения перекрывают файл.

## Пайплайн

| Переменная | По умолчанию | Значение |
|---|---|---|
| `PIPELINE_VERSION` | `v2` | `v1` включает старый набор воркеров |
| `PIPELINE_SHADOW` | `false` | Второй вариант пайплайна рядом, в интерфейс не уходит |
| `PIPELINE_V2_STAGES` | `evidence,language,guide,structure,terminology,consistency,lexicon,verifier` | Какие стадии v2 включать |
| `PIPELINE_V2_PASS_TIMEOUT` | `360` | Секунды на один проход модели |
| `PIPELINE_V2_PASS_RETRIES` | `2` | Повторы при сбое прохода |
| `LLM_JOB_TIMEOUT` | `900` | Секунды на всю задачу вычитки |

## OIDC

| Переменная | Значение |
|---|---|
| `OIDC_ISSUER` | Issuer без слэша на конце. Пусто: только пароль |
| `OIDC_CLIENT_ID` | Клиент |
| `OIDC_CLIENT_SECRET` | Секрет |
| `OIDC_REDIRECT_URI` | Ровно `https://<хост>/api/auth/oidc/callback` |
| `OIDC_ADMIN_GROUPS` | Группы через запятую, им ставится admin |

## Прочее

| Переменная | Значение |
|---|---|
| `BACKUP_DIR` | Каталог снимков в контейнере, по умолчанию `/app/backups` |
| `BACKUP_KEEP` | Сколько снимков хранить |
| `DOCX_MAX_UNCOMPRESSED_BYTES` | Потолок распаковки docx |
| `REPO_MAX_FILE_BYTES` | Потолок файла в репозитории документов, по умолчанию 25 МБ |
| `REPO_STORE_DIR` | Каталог репозитория, по умолчанию `/app/data/repo` |

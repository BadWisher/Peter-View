# Конфигурация

Файл `.env` лежит рядом с `docker-compose.yml`. `./deploy.sh` создаёт его из `.env.example`, если файла нет. Пустые `LLM_*` значат: модель не вызывать.

Администратор может перебить URL, ключ и имя модели в интерфейсе. Эти значения пишутся в `data/llm_settings.json` внутри тома и важнее `.env`, пока их не сотрут.

## Сеть и cookie

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PROOFREADER_PORT` | `3080` | Порт на хосте |
| `PROOFREADER_COOKIE_SECURE` | `false` | `true` за HTTPS, иначе браузер отбросит cookie |
| `PROOFREADER_CORS_ORIGINS` | пусто | Дополнительные Origin, обычно не нужны |
| `PROOFREADER_DOCS` | `false` | Swagger UI. В проде оставь `false` |

## Разделы

| Переменная | По умолчанию | Раздел |
|---|---|---|
| `FEATURE_DOCUMENTS` | `false` | Документы |
| `FEATURE_API` | `false` | Вычитка OpenAPI |
| `FEATURE_WATCH` | `false` | Наблюдение за страницами |
| `FEATURE_SCREENSHOTS` | `false` | Редактор скриншотов |

Вычитка, Style Guide, история и аналитика всегда на месте. См. [Скрытие разделов](features.md).

## Сеть вычитки

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PROOFREADER_SSRF_ALLOW_PRIVATE` | `true` | Можно ходить на внутренние wiki и порталы. Если сервис торчит в интернет, поставь `false` |
| `PROOFREADER_MAX_FETCH_BYTES` | 10 МиБ | Потолок скачивания страницы |
| `DOCX_MAX_UNCOMPRESSED_BYTES` | 300 МиБ | Потолок распакованного docx |
| `DOCX_MAX_COMPRESSION_RATIO` | `200` | Защита от zip-бомб |

## Модель

| Переменная | Смысл |
|---|---|
| `LLM_BASE_URL` | Корень OpenAI-совместимого API. Пусто = полная проверка выключена |
| `LLM_API_KEY` | Ключ |
| `LLM_MODEL` | Имя модели |
| `LLM_TEMPERATURE` | По умолчанию `0` |
| `LLM_CONCURRENCY` | Параллельные запросы, по умолчанию `4` |
| `LLM_TIMEOUT` | Секунды |
| `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` | Эмбеддинги для поиска по гайду. Пусто = поиск по словам |

Остальные `PIPELINE_*` трогай, только если понимаешь пайплайн v2. См. [Языковая модель](llm.md).

## Вход через организацию

| Переменная | Смысл |
|---|---|
| `OIDC_ISSUER` | Issuer IdP без слэша на конце. Пусто = только пароль |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Клиент |
| `OIDC_REDIRECT_URI` | Ровно `https://<хост>/api/auth/oidc/callback` |
| `OIDC_ADMIN_GROUPS` | Группы через запятую, которым ставится роль администратора |

Примеры Keycloak и Azure: [Для ИТ](it.md).

## Прочее

| Переменная | Смысл |
|---|---|
| `PROOFREADER_CORP_PROXY` | Мост к прокси на VDI |
| `BACKUP_DIR` | Внутри контейнера, по умолчанию `/app/backups` |
| `BACKUP_KEEP` | Сколько снимков держать |
| `JIRA_BASE_URL` | Если используете тикеты из интерфейса |

# Конфигурация

Файл `.env` рядом с `docker-compose.yml`. Пустые ключи LLM значат: модель не вызывать.

| Переменная | Смысл |
|---|---|
| `PROOFREADER_PORT` | Порт на хосте |
| `PROOFREADER_COOKIE_SECURE` | `true` за TLS |
| `PROOFREADER_CORS_ORIGINS` | Дополнительные origin, обычно пусто |
| `PROOFREADER_DOCS` | Swagger UI, по умолчанию `false` |
| `FEATURE_DOCUMENTS` | Раздел документов |
| `FEATURE_API` | Вычитка OpenAPI |
| `FEATURE_WATCH` | Наблюдение за страницами |
| `FEATURE_SCREENSHOTS` | Редактор скриншотов |
| `PROOFREADER_CORP_PROXY` | Мост к корп-прокси |
| `PROOFREADER_SSRF_ALLOW_PRIVATE` | Fetch во внутреннюю сеть |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | Сервер полной проверки |
| `EMBEDDING_*` | Сервер эмбеддингов для RAG |
| `OIDC_ISSUER` | Issuer IdP. Пусто = только пароль |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Клиент OIDC |
| `OIDC_REDIRECT_URI` | `https://<хост>/api/auth/oidc/callback` |
| `OIDC_ADMIN_GROUPS` | Группы с ролью admin |
| `BACKUP_DIR`, `BACKUP_KEEP` | Снимки тома |

Администратор может переопределить URL и ключи модели в интерфейсе. Они пишутся в `data/llm_settings.json` внутри тома.

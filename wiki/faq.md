# FAQ

**Где лежат данные?** Том Docker `backend-data` (`/app/data` в backend). Бэкап: `make backup` → `./backups`.

**Почему нет полной проверки?** Пустой `LLM_BASE_URL` и пустые настройки в интерфейсе. Локальные движки от этого не отключаются.

**Куда делся раздел «Документы»?** `FEATURE_DOCUMENTS=false`. То же для API, наблюдения и скриншотов.

**LanguageTool не поднимается.** Ему нужно ~1.5 ГБ RAM и до полутора минут на старт. Смотри `make logs` у сервиса `languagetool`.

**Как войти через Keycloak или Azure?** Заполни `OIDC_*`. Redirect URI и примеры клиентов: [Для ИТ](it.md).

**Можно LDAP?** Нет. В 0.1 только пароль и OIDC.

**Почему 403 на правке гайда?** Роль editor. Гайд пишет администратор.

**Сессия не держится за HTTPS.** Поставь `PROOFREADER_COOKIE_SECURE=true`.

**Порт занят.** `PROOFREADER_PORT` в `.env`, затем `./deploy.sh`.

# Безопасность: как устроено

Обзор механизмов защиты в коде. Практические настройки для публичного хоста [Усиление защиты](../ops/hardening.md).

## Аутентификация и сессии

- Локальные пароли bcrypt (cost по умолчанию библиотеки), `data/users.json`. Минимальная длина 8 символов, проверка сложности отсутствует.
- Сессия: `secrets.token_urlsafe(32)`, словарь `SESSIONS` в памяти процесса, cookie `proofreader_session`: HttpOnly, SameSite=Lax, Secure по флагу env, TTL 12 часов со скольжением (продлевается при каждом запросе). Рестарт вышибает всех.
- Брутфорс: 5 неудачных входов за 300 с на пару (IP, логин) и отдельно на IP; счётчики в памяти, сбрасываются рестартом. Ответ 429 по-русски. Смена пароля под тем же лимитером.
- OIDC: authorization code flow с state+nonce (10 минут, в памяти), PKCE не используется. Роль из пересечения групп токена с `OIDC_ADMIN_GROUPS`.

## CSRF

Токенов нет, схема «cookie + проверка происхождения». Middleware на все не-безопасные методы (POST/PUT/PATCH/DELETE): если запрос принёс `Origin` или `Referer`, их хост сравнивается с `Host` запроса; не совпал и origin не в `PROOFREADER_CORS_ORIGINS` 403 «Перекрёстный запрос отклонён». Без Origin/Referer запрос проходит (не-браузерные клиенты, curl) это осознанное послабление. SameSite=Lax довершает картину: кросс-доменные POST из чужих форм cookie не получат.

Последствие для операторов: обратный прокси обязан честно пробрасывать `Host`, иначе собственные запросы UI начнут ловить 403.

## CORS

По умолчанию выключен (пустой allow-list), same-origin. Включение `PROOFREADER_CORS_ORIGINS` списком точных origin (не `*`, credentials не совместимы с wildcard). Нужен только когда UI и API на разных доменах.

## Защита от SSRF

Все пользовательские адреса идут через `backend/app/net_guard.py`. Точки входа: вычитка по URL (`llm/documents.parse_url`), краулер `/api/check-url` (`crawler.safe_get`), мониторинг (`watch_run.safe_request`), извлечение текста из URL в CLI-утилитах. Алгоритм:

1. Схема строго http/https, хост непустой.
2. DNS-резолвинг до соединения; каждая A/AAAA-адресация проверяется: loopback, link-local (включая 169.254.169.254 метаданные облаков), multicast, unspecified, reserved блокируются всегда. Приватные диапазоны (10/8, 172.16/12, 192.168/16, ...) блокируются только при `PROOFREADER_SSRF_ALLOW_PRIVATE=false` (дефолт true под интранет).
3. Редиректы не отданы на откуп HTTP-клиенту: `follow_redirects=False`, каждый следующий location проверяется тем же кодом, потолок `PROOFREADER_MAX_REDIRECTS` (5). Это закрывает класс атак «публичный URL редиректит на 169.254.169.254».
4. Размер тела под колпаком `PROOFREADER_MAX_FETCH_BYTES` (10 MiB).

Что сознательно не под guard'ом: OIDC issuer/token/userinfo, LLM и embedding endpoints, LanguageTool. Их выбирает админ; компрометация админки это game over любой архитектуры, поэтому отдельного реестра разрешённых адресов нет (можно добавить при необходимости, это известное решение).

## CSP и заголовки nginx

Основная политика: `default-src 'self'; script-src 'self'` (без unsafe-inline/eval), `style-src` с unsafe-inline (генерируемый UI использует inline-style), `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`. Плюс `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy` (гео/микро/камера выключены).

Исключения в nginx, каждое по конкретной нужде:

- `/api/docs`, `/api/redoc`: CDN Swagger/ReDoc (jsDelivr, redoc.ly, gstatic) только под включённым Swagger.
- `/api/watch/pages/*/copy`: сохранённые чужие страницы в iframe. `script-src 'none'`, `connect-src 'none'`, `object-src 'none'`, `form-action 'none'`, `base-uri https:`, `frame-ancestors 'self'`, `no-store`; на клиенте ещё и `<iframe sandbox="allow-same-origin allow-popups">`. Скрипты и формы выключены, потому что снимок это данные недоверенного сайта, отрендеренные в нашем origin.

## Отображение найденного текста

Все пользовательские тексты (документ, сообщения правил, находки модели) экранируются перед вставкой в HTML (`escapeHTML` в shared.js), разметка подсветки собирается событийным потоком открытых/закрытых тегов, а не конкатенацией. Паттерны регулярных правок пользователя валидируются при сохранении (bad pattern 400) и исполняются с бюджетом времени на строку.

## Секреты

- API-ключи модели никогда не покидают сервер наружу: `GET /api/settings` маскирует, пустой PATCH не затирает.
- `llm_settings.json` 0600; бэкап `data/` содержит ключи храните архивы как секреты.
- Пароли порталов Мониторинга XOR-обфускация ключом `PROOFREADER_SECRET` (или автогенерированным `watch.db.key`). Честно: это защита от «просто посмотреть в sqlite», не криптография при утечке тома.
- `.env` вне git (gitignore), содержит `OIDC_CLIENT_SECRET` и `LLM_API_KEY`.

## Публичные эндпоинты без сессии

`/api/health`, `/api/config`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/oidc/*`. `/api/config` отдаёт версии, флаги и два bool'а (oidc/docs) минимально необходимое для отрисовки логин-страницы. Всё остальное требует аутентификацию; `/api/health/full` ещё и роль admin.

## Журнал аудита

`data/audit.jsonl`: входы (успех/неудача), logout, создание/удаление пользователей, смена ролей и паролей, правки гайдов и правил, смена настроек, запуск разделов. 2000 последних строк, просмотр в «Системе» (admin). В стандартной сборке не шипится наружу это файл на томе.

## Дальше

- [Усиление для публичного хоста](../ops/hardening.md) чек-лист.
- [Модель угроз в решениях](decisions.md) почему нет, например, CSRF-токенов.

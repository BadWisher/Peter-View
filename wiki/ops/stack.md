# Стек: compose-файлы, образы, nginx

Страница-справочник: что из чего собирается и как это соединено. Для запуска читайте [Установку](deploy.md), здесь детали и подводные камни.

## docker-compose.yml (базовый)

Три сервиса, сеть `internal` (bridge), том `backend-data`.

### backend

- Сборка из `./backend`, `restart: unless-stopped`, `env_file: .env`.
- Блок `environment` переопределяет `.env`: `LANGUAGETOOL_URL=http://languagetool:8010/v2/check`, `STYLEGUIDE_PATH=/app/styleguide/rules.yaml`, `STYLEGUIDE_STORE_DIR=/app/data/styleguides`, `PROOFREADER_DOCS=false`.
- Тома: `backend-data:/app/data`, `./backups:/app/backups`, read-only `./backend/styleguide/rules.yaml:/app/styleguide/rules.yaml` (встроенный базовый гайд редактируется на хосте и подхватывается без пересборки; заметьте, это mount конкретного файла, а не каталога).
- `depends_on: languagetool (service_healthy)`. Healthcheck: `wget http://localhost:8000/api/health`, каждые 10 с, старт-пауза 20 с, 12 попыток.
- `mem_limit: 2g`. Логи json-file 10 МБ × 3 файла. Порт не публикуется.

### frontend

- Сборка из `./frontend` (nginx + статика), единственный опубликованный порт: `${PROOFREADER_PORT:-3080}:80` на всех интерфейсах.
- `depends_on: backend (service_healthy)`. Healthcheck `wget http://127.0.0.1/`.
- Без mem_limit.

### languagetool

- Образ `erikvl87/languagetool`, запинен по digest (обновляется руками или Dependabot'ом... не обновляется: см. [hardening](hardening.md)).
- `ENABLED_LANGUAGES=ru`, JVM `Xms=512m`/`Xmx=1g`, `mem_limit: 1536m`.
- Healthcheck по `/v2/languages`, start_period 90 с (Java долго греется).

## docker-compose.prod.yml

Минимальный overlay для развёртывания из registry: подменяет `image:` у backend и frontend на `ghcr.io/${GHCR_REPOSITORY}/...:${IMAGE_SHA}` с `pull_policy: always`. Обе переменные обязательны (`:?`). `build:` из базового файла сохраняется, но не используется при pull. Остальные параметры наследуются.

## docker-compose.corp-proxy.yml

Overlay для VDI за прокси; включается `PROOFREADER_CORP_PROXY=true` в `.env` (deploy.sh и Makefile подставляют файл по этой переменной). Добавляет сервис `proxy-bridge` (alpine/socat, `network_mode: host`, слушает `172.17.0.1:3128`, форвардит в `CORP_PROXY_UPSTREAM`) и проксирует им backend: `build.network: host`, `extra_hosts` c `host-gateway`, переменные `HTTP(S)_PROXY` + `NO_PROXY`. Побочный эффект: зависимость от languagetool ослабляется с `service_healthy` до `service_started` (быстрый старт на VDI, но проверка может стартануть до готовности LT).

## Образы

### backend/Dockerfile

- База `python:3.12-slim` по digest.
- apt: `ca-certificates`, `gosu`, библиотеки Chromium (libnss3, libgbm1 и т. п.) для Playwright.
- Vale 3.9.1: бинарь качается с GitHub releases. **Комментарий в Dockerfile обещает проверку sha256 «сборка падает, если содержимое изменилось», но сравнения хэша в коде нет** бинарь просто распаковывается. Практический вывод: доверяйте mirror'у, где хотите контроль, пиньте digest образа после сборки.
- `pip install -r requirements.txt` (pins: fastapi, uvicorn, httpx, pymorphy3, razdel, playwright, bcrypt, openai, lxml, python-docx, ...).
- `playwright install --with-deps chromium` в общий каталог `/opt/ms-playwright` (иначе root-кэш не виден рантайм-пользователю).
- Non-root: пользователь `appuser` (uid 10001); `entrypoint.sh` чинит права старого тома и через `gosu` роняет привилегии перед запуском uvicorn.
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300`.

### frontend/Dockerfile

`nginx:alpine` по digest, два COPY (`nginx.conf` и `public/`). Никакой сборки: фронтенд работает как есть, без бандлера.

## nginx.conf: карта location'ов

| Путь | Особенность |
|---|---|
| `/` | статика, SPA-fallback на `index.html` |
| `/api/jobs/*/stream` | SSE: `proxy_buffering off`, `X-Accel-Buffering: no`, таймауты 600 с |
| `/api/docs`, `/api/redoc` | Swagger/ReDoc с ослабленным CSP (jsDelivr, redoc.ly, gstatic) |
| `/api/watch/pages/*/copy` | отдельный CSP для iframe-копии: `script-src 'none'`, `frame-ancestors 'self'`, `no-store` |
| `/api/` (всё остальное) | реверс на `backend:8000`, `client_max_body_size 50m`, read/send timeout 600 с, буферизация ON |

Заголовок `= /api/check-url` настроен как SSE-прокс (буферизация выключена), но фронтенд этим эндпоинтом не пользуется (использует jobs) локации наследует историю и безопасна, но мертва.

Заголовки уровня server (наследуемые location'ами без своих `add_header`): CSP `default-src 'self'; script-src 'self'`, `nosniff`, `X-Frame-Options DENY`, `Referrer-Policy no-referrer`, `Permissions-Policy`, и `Cache-Control: no-cache` на всё.

**Про кэш:** `no-cache` на все ресурсы это осознанно, чтобы обновление фронта не требовало hard-refresh. Цена нет кэширования шрифтов и JS, трафик туда-сюда копеечный, зато никогда не «старый app.js». Ручной cache-busting (`?v=48/49` в `index.html`) частично бессмысленен при `no-cache`, но импорты ES-модулей версионируются только так.

**Чего в конфиге нет:** HTTPS (слушает 80), gzip-настроек (дефолт alpine-образа), rate limiting, отдельных access/error логов. Всё это ложится на внешний прокси ([TLS](tls-proxy.md)) или остаётся дырой по недосмотру ([hardening](hardening.md)).

## Что где живёт на диске

| Путь в контейнере | Хост | Назначение |
|---|---|---|
| `/app/data` | том `backend-data` | users.json, llm_settings.json (0600), rules.json, user_prefs.json, audit.jsonl, jobs.db, watch.db, styleguides/, repo/, статистика |
| `/app/backups` | `./backups` | снапшоты бэкапов |
| `/app/styleguide/rules.yaml` | `./backend/styleguide/rules.yaml` (ro) | встроенный базовый гайд |
| `/app/vale`, `/app/app`, `/app/eval` | внутри образа | Vale-конфиги, код, eval-наборы |

## Дальше

- [Переменные окружения](config-env.md).
- [Хранилище данных](../arch/data-model.md): что внутри `/app/data`.
- [Обновление](upgrade.md): как пересобирать/перетягивать образы.

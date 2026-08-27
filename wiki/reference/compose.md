# Compose и команды

Файл `docker-compose.yml`. Три сервиса в сети `internal`. С хоста опубликован только nginx.

## Сервисы

| Сервис | Сборка | Процесс внутри | Healthcheck | Память |
|---|---|---|---|---|
| `languagetool` | образ `erikvl87/languagetool`, pin по sha256, `ENABLED_LANGUAGES=ru` | JVM, `:8010/v2/check` | `/v2/languages`, start_period 90 с | 1536 МБ, `-Xms512m -Xmx1g` |
| `backend` | `backend/Dockerfile`: Python 3.12, Vale 3.9.1, uvicorn | `app.main:app` `:8000` | `/api/health` | 2 ГБ |
| `frontend` | `frontend/Dockerfile`: nginx:alpine | статика + прокси `/api` | `GET /` | без лимита |

Порядок: LanguageTool healthy → backend healthy → frontend. Backend ходит в LanguageTool по `http://languagetool:8010/v2/check`.

Тома:

- `backend-data` → `/app/data`
- `./backups` → `/app/backups`
- `./backend/styleguide/rules.yaml` → `/app/styleguide/rules.yaml` (только чтение)

Порт хоста: `${PROOFREADER_PORT:-3080}:80` на frontend.

Образы публикации: `ghcr.io/badwisher/peter-view/backend` и `ghcr.io/badwisher/peter-view/frontend`.

Логи: json-file, 10 МБ × 3 файла на сервис.

## Команды на хосте

| Команда | Действие |
|---|---|
| `./deploy.sh` | `.env` при отсутствии, `compose up -d --build`, ждёт ответ на порту |
| `make down` | Остановить стек |
| `make logs` | Логи всех сервисов |
| `make ps` | Статус |
| `make backup` | tar `/app/data` в `./backups` |
| `make update` | `git pull --ff-only` и снова `./deploy.sh` |
| `make lint` | ruff (разработка) |
| `make test` | pytest backend (разработка) |

`PROOFREADER_CORP_PROXY=true` подключает `docker-compose.corp-proxy.yml`: контейнер `proxy-bridge` (socat) и HTTP_PROXY у backend на `host.docker.internal`. Нужно, когда корпоративный прокси слушает только 127.0.0.1 на хосте, а контейнер туда не достаёт.

## Сборка backend

Непривилегированный пользователь `appuser` (uid 10001). Vale скачивается с GitHub Releases, контрольная сумма архива проверяется на этапе сборки. Entrypoint: `/entrypoint.sh`, затем uvicorn `--timeout-keep-alive 300`.

Устройство стека: [архитектура](../explanation/architecture.md). Файлы на томе: [хранилище](data.md).

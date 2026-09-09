# Установка и запуск

Развёртывание сервис пережил один-единственный сценарий: docker compose на одном хосте. Всё остальное (kubernetes, systemd, bare metal) не поддерживается документацией и не тестировался.

## Требования

| Параметр | Значение |
|---|---|
| Docker Engine | с plugin compose v2; скрипт понимает и legacy `docker-compose` |
| Память | 1.5 ГБ на LanguageTool (JVM: Xms 512m, Xmx 1g) + до 2 ГБ на приложение backend; фронт лёгкий |
| Диск | образы ~2 ГБ (Chromium+Playwright внутри backend), плюс том данных и `./backups` |
| Порт | 3080 по умолчанию (`PROOFREADER_PORT`), наружу торчит только nginx |
| Сеть | доступ к registry загрузок образов; на VDI за корпоративным прокси см. ниже |

## Первый запуск

```bash
git clone https://github.com/BadWisher/Peter-View
cd Peter-View
./deploy.sh
```

`deploy.sh` идемпотентен: он же первичный запуск, он же обновление. По шагам:

1. Читает `PROOFREADER_PORT` из `.env` (последняя строка побеждает, кавычки вырезаются), по умолчанию 3080.
2. Определяет compose-команду (`docker compose`, иначе `docker-compose`, иначе выход с ошибкой).
3. Если `.env` нет, копирует `.env.example` и напоминает заполнить `LLM_BASE_URL/LLM_API_KEY/EMBEDDING_*`, включить `PROOFREADER_COOKIE_SECURE` за TLS и `PROOFREADER_CORP_PROXY` на VDI.
4. Если в `.env` стоит `PROOFREADER_CORP_PROXY=true`, добавляет overlay `docker-compose.corp-proxy.yml`.
5. Поднимает стек с пересборкой образов (`up -d --build`); compose пересобирает только изменённые слои.
6. Ждёт до 60 секунд ответа `http://localhost:PORT/` (если в системе есть `curl`) и печатает все доступные адреса: localhost, непубличные IPv4 hostname, без docker-мостов.

Шаблонное сообщение в конце: «Первый вход: admin / admin (сразу заведи своих в меню „Пользователи“)». Смените пароль до подключения пользователей.

Примечание: ожидание готовности в скрипте коротковато для холодного старта. Фронт стартует после backend, backend после healthy LanguageTool с start_period 90 с. На первой сборке скрипт может напечатать «не ответил за 60 с» при полностью здоровом процессе: это не ошибка, выход всё равно 0, смотрите `make logs`.

## За корпоративным прокси (VDI)

Хосты с интернетом через прокси (`127.0.0.1:3128`) требуют двух вещей: прокси во время сборки (apt, pip, загрузка Chromium) и прокси во время работы (запросы к LLM/эмбеддингам). Overlay `docker-compose.corp-proxy.yml` решает обе:

- поднимает `proxy-bridge` (alpine/socat) на `172.17.0.1:3128`, форвардящий в `CORP_PROXY_UPSTREAM` (по умолчанию `127.0.0.1:3128`);
- даёт backend `build.network: host` и `extra_hosts: host.docker.internal:host-gateway`;
- прописывает backend `HTTP_PROXY/HTTPS_PROXY=http://host.docker.internal:3128` и `NO_PROXY=localhost,127.0.0.1,backend,languagetool`.

Включение: `PROOFREADER_CORP_PROXY=true` в `.env` и `./deploy.sh` (или `make deploy`). Проверка конфигурации без запуска: `make config-corp-proxy`.

Берегите мост: `proxy-bridge` это открытый без аутентификации прокси на docker-интерфейсе. Любой, кто дотянется до `172.17.0.1:3128`, ходит в интернет через ваш корпоративный прокси. Не поднимайте его на хостах с доступной наружу bridge-сетью.

## Готовые образы вместо сборки

CI публикует образы на GHCR: `ghcr.io/<владелец>/backend:<sha>` и `:main` (+ тег версии на релизах). Развёртывание из registry вместо локальной сборки:

```bash
export IMAGE_SHA=<полный commit sha>
export GHCR_REPOSITORY=<владелец/имя в нижнем регистре>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Overlay prod подменяет `image:` у backend и frontend (с `pull_policy: always`) и требует обе переменные: без них compose падает с внятными `:?`-сообщениями. Проверка связки конфигов: `make prod-config`.

## Структура стека после запуска

Три контейнера в одной изолированной bridge-сети `internal`:

| Сервис | Роль | Порт |
|---|---|---|
| `frontend` | nginx: статика UI + реверс-прокси `/api/` | единственный опубликованный: `3080->80` |
| `backend` | FastAPI + Vale + pymorphy3 + Playwright/Chromium | 8000, только внутри сети |
| `languagetool` | LanguageTool 6.x (image по digest), только `ru` | 8010, только внутри сети |

Том `backend-data` (named volume) смонтирован в `/app/data`, каталог `./backups` bind-маунтится в `/app/backups`. Подробности образов, compose-файлов и nginx: [Стек и его детали](stack.md).

## Команды Makefile

Все обёртки над compose, включая corp-proxy overlay при соответствующем флаге в `.env`:

| Команда | Что делает |
|---|---|
| `make deploy` | тот же `./deploy.sh` |
| `make down` / `make ps` / `make logs` | остановить / статус / `logs -f` |
| `make update` | `git pull --ff-only` + `./deploy.sh` |
| `make backup` | tar всего `/app/data` в `./backups/manual-<время>.tgz` |
| `make config` | валидность compose-конфига (`--quiet`) |
| `make lint` / `make test` / `make regression` | ruff, pytest локально, самотесты внутри контейнера |
| `make ci-local` | lint + test + обе валидации конфига + полная пересборка образов |

Ловушка `make backup`: файлы `manual-*.tgz` не попадают под автоматическую ротацию (ротация знает только про `peterview-*.tar.gz`), копятся до ручного удаления. См. [Бэкапы](backup.md).

## Чего в деплое нет

- HTTPS: nginx слушает 80, сертификатов нет, терминация TLS снаружи ([TLS и обратный прокси](tls-proxy.md)).
- Инсталяционных хуков: нет preflight на версию Docker, свободный порт, объём диска.
- Migrations: схема данных (JSON + SQLite) мигрирует кодом приложения, отдельного шага обновления нет.

## Дальше

- [Переменные окружения](config-env.md) полный справочник.
- [Обновление версии](upgrade.md), [Бэкап и восстановление](backup.md), [Дежурство](runbook.md).

# Compose и команды

Три контейнера в `docker-compose.yml`.

| Сервис | Процесс | Зачем отдельно |
|---|---|---|
| `backend` | FastAPI | Сессии, задания, гайды, файлы |
| `frontend` | nginx | Статический интерфейс |
| `languagetool` | JVM | Грамматика. Долгий старт, своя куча |

Том `backend-data` монтируется в backend. Снимки: каталог `./backups` на хосте → `/app/backups` в контейнере.

Образы публикации: `ghcr.io/badwisher/peter-view/backend` и `ghcr.io/badwisher/peter-view/frontend`.

С хоста открыт только порт nginx, по умолчанию `3080` (`PROOFREADER_PORT`).

## Команды на хосте

| Команда | Действие |
|---|---|
| `./deploy.sh` | `.env` при отсутствии, `compose up -d --build` |
| `make down` | Остановить стек |
| `make logs` | Логи всех сервисов |
| `make ps` | Статус |
| `make backup` | tar данных в `./backups` |
| `make update` | `git pull --ff-only` и снова `./deploy.sh` |
| `make lint` | Проверка кода (для разработки) |
| `make test` | Тесты backend (для разработки) |

`PROOFREADER_CORP_PROXY=true` в `.env` подключает `docker-compose.corp-proxy.yml`.

Первый запуск LanguageTool занимает около полутора минут. Не перезапускайте контейнер каждые десять секунд: healthcheck рассчитан на длинный старт.

Данные пользователей не входят в образ. Обновление образа не удаляет учётные записи, пока том на месте.

Зачем три процесса: [почему три контейнера](../explanation/architecture.md).

# Окружение разработчика

Здесь про то, чтобы запустить Peter View локально и править код. Если нужно просто проверить текст, берите [Быстрый старт](../users/quickstart.md) и не лезьте в исходники.

Продактив-развёртывание на сервере описано в разделе DevOps ([Деплой](../ops/deploy.md)). Эта страница про рабочий цикл: склонировал, поднял, поправил, прогнал тесты.

## Что должно стоять

- Docker Engine + compose v2 (или старый `docker-compose`; `deploy.sh` сам определяет, какой звать).
- Git.
- Python 3.12 на хосте, если хотите гонять тесты и линтер без контейнера. Код backend рассчитан на 3.12, как в образе.
- ~4 ГБ свободной памяти под контейнеры (backend до 2 ГБ, LanguageTool до 1,5 ГБ).

Сборочных инструментов для фронта не нужно: ни Node, ни npm, ни bundler. Фронтенд это обычные `.js`/`.css`, nginx просто раздаёт статику.

## Первый запуск

```bash
git clone https://github.com/BadWisher/Peter-View
cd Peter-View
cp .env.example .env          # deploy.sh сделает это сам, если .env нет
./deploy.sh
```

Скрипт соберёт три образа (`backend`, `frontend`, готовый `languagetool`), поднимет их и будет до 30 раз по два секунды опрашивать `http://localhost:3080/`, пока фронт не ответит. LanguageTool на JVM просыпается последним, минуты полторы-две. Когда увидите список адресов, интерфейс на `http://localhost:3080`,Swagger (если включите) на `/api/docs`.

Логин первый раз: `admin` / `admin`. Дальше смените пароль.

## Без docker.sh, вручную

Удобно, когда надо подменить compose-файл или поднять только backend:

```bash
docker compose up -d languagetool          # движок орфографии
docker compose build backend               # пересоб after правок python
docker compose up -d backend               # один сервис
docker compose logs -f backend
```

Переменные читаются из `.env` рядом с `docker-compose.yml` (сервис backend подключает его через `env_file`). Часть значений переопределена прямо в блоке `environment:` compose-файла и из `.env` не переживётся, ловушка разобрана в [Переменных окружения](../ops/config-env.md).

## Через Makefile

В корне лежит [Makefile](https://github.com/BadWisher/Peter-View/blob/main/Makefile) с типовыми командами. Он работает с тем же `docker compose` и сам дописывает override для корпоративного прокси, если в `.env` стоит `PROOFREADER_CORP_PROXY=true`.

| Команда | Что делает |
|---|---|
| `make deploy` | то же, что `./deploy.sh` |
| `make update` | `git pull --ff-only` и пересборка через deploy.sh |
| `make logs` / `make ps` / `make down` | управление поднятым стеком |
| `make backup` | ручной снимок `/app/data` в `./backups` внутри контейнера backend |
| `make config` | `docker compose config --quiet`, проверка, что файлы валидны |
| `make lint` | `ruff check` по backend/app, backend/eval, backend/tests |
| `make test` | `pytest -q` на хосте (нужен python 3.12 с dev-зависимостями) |
| `make regression` | регрессионные проверки правил внутри контейнера backend |
| `make ci-local` | lint + test + config + сборка образов, как это делает CI |
| `make prod-config` | валидация prod-override, требует `IMAGE_SHA` и `GHCR_REPOSITORY` |
| `make config-corp-proxy` | валидация compose с корпоративным прокси |

## Тесты и линтер вне контейнера

Чтобы не пересобирать образ на каждую правку, поставьте зависимости и гоняйте на хосте:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
make lint
make test
```

Конфигурация pytest лежит в корневом `pyproject.toml`: `pythonpath=["backend"]`, `testpaths=["backend/tests"]`. То есть запускать надо из корня репозитория, а не из `backend/`. Подробно о тестовых наборах и что они покрывают [Тесты и регрессия](tests.md).

`make regression` требует поднятого LanguageTool (checks дёргают его по HTTP), поэтому идёт через контейнер, а не на хосте.

## Хот-релоад backend

В образе uvicorn запускается без `--reload`. Для разработки с перезапуском на сохранение поднимите процесс в контейнере вручную:

```bash
docker compose up backend   # без -d, Ctrl-C останавливает
# либо, смонтировав исходники, перезапустите:
docker compose exec backend python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Чтобы `--reload` видел правки с хоста, пробросьте `./backend/app` томом в контейнер во время разработки. В штатном compose-файле исходники пекутся в образ, томов нет.

## Что читать дальше

- [Карта кода](code-map.md): где какой модуль и за что отвечает.
- [Бэкенд](backend.md): конвенции FastAPI-слоя, как добавить проверку.
- [Фронтенд](frontend.md): как устроен SPA без сборки и как добавить раздел.
- [Правила гайда в коде](guides-rules.md): формат `rules.yaml`, реестр, Vale-стили.
- [Тесты и регрессия](tests.md): три набора проверок и как их гонять.
- [HTTP API](api.md): контракты эндпоинтов.
- [Сборка этой вики](docs-site.md): как править документацию.

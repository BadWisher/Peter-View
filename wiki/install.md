# Установка и Docker

`./deploy.sh` копирует `.env.example` в `.env`, если файла ещё нет, собирает образы и поднимает стек:

- `backend`: FastAPI, Vale, pymorphy3
- `frontend`: nginx и статика
- `languagetool`: отдельный контейнер

Порт: `PROOFREADER_PORT`, по умолчанию 3080.

Прод из готовых образов: `docker-compose.yml` + `docker-compose.prod.yml`.

Образы: `ghcr.io/badwisher/peter-view/backend` и `.../frontend`. Нужны `IMAGE_SHA` и `GHCR_REPOSITORY=badwisher/peter-view`.

Корп-прокси на VDI: `PROOFREADER_CORP_PROXY=true` (подключает `docker-compose.corp-proxy.yml`).

Данные: том `backend-data`. Снимок: `make backup`.

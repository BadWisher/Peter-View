# Установка и Docker

`./deploy.sh` можно гонять повторно: пересоберёт то, что изменилось, и поднимет стек заново.

## Что поднимается

| Сервис | Что внутри | Память в compose |
|---|---|---|
| `frontend` | nginx, статика, порт на хосте | без лимита, лёгкий |
| `backend` | FastAPI, Vale, pymorphy3 | 2 ГБ |
| `languagetool` | `erikvl87/languagetool`, только `ru` | 1.5 ГБ |

Порт снаружи: `PROOFREADER_PORT` (по умолчанию 3080), внутри контейнера frontend это 80.

Том `backend-data` монтируется в `/app/data`: пользователи, гайды, отчёты, настройки модели. Каталог `./backups` с хоста попадает в `/app/backups`.

## Обновление

```bash
git pull --ff-only
./deploy.sh
```

Или `make update`. Том не трогается.

## Прод из готовых образов

Без сборки с исходников:

```bash
export GHCR_REPOSITORY=badwisher/peter-view
export IMAGE_SHA=<тег или sha>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Образы: `ghcr.io/badwisher/peter-view/backend` и `.../frontend`.

## Корп-прокси на VDI

Если HTTP-прокси слушает только `127.0.0.1` на хосте, контейнер до него не достучится. В `.env`:

```env
PROOFREADER_CORP_PROXY=true
```

Подключится `docker-compose.corp-proxy.yml`: мост socat и `HTTP_PROXY` у backend. Подробности в комментариях того файла.

## Бэкап

```bash
make backup
```

В `./backups` появится tar из `/app/data`. Том храните отдельно от образов.

Остановить: `make down`. Логи: `make logs`.

# Как помочь

Присылайте pull request. Код публикуется под Apache-2.0, отдельного соглашения нет.

## Локально

```bash
cp .env.example .env
python3 -m pip install -r backend/requirements-dev.txt
make lint
make test
make config
```

Весь стек: `./deploy.sh`. Интерфейс откроется на http://localhost:3080.

Интерфейс: обычный JS в `frontend/public/js/`, по файлу на раздел. Строки: `frontend/public/i18n/`.

Документация сайта: Markdown в `wiki/`, сборка `mkdocs build` в `docs/wiki/`. Лендинг: `landing/`, копия в `docs/` для GitHub Pages. Устройство: `wiki/explanation/architecture.md`.

## Стиль

Python 3.12, ruff как в CI. В пользовательских строках нет длинного тире.

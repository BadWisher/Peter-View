# Как помочь

Присылай pull request. Код уходит под Apache-2.0, отдельной бумаги нет.

## Локально

```bash
cp .env.example .env
python3 -m pip install -r backend/requirements-dev.txt
make lint
make test
make config
```

Весь стек: `./deploy.sh`.

Интерфейс: обычный JS в `frontend/public/js/`, по файлу на раздел. Строки: `frontend/public/i18n/`.

## Стиль

Python 3.12, ruff как в CI. В пользовательских строках нет длинного тире `—`.

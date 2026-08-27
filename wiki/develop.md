# Разработка и тесты

Сборка и тесты: [CONTRIBUTING](https://github.com/BadWisher/Peter-View/blob/main/CONTRIBUTING.md).

Код сервера: `backend/app/`. Интерфейс: `frontend/public/js/`, по файлу на раздел. Стек: [архитектура](explanation/architecture.md). Маршруты: [HTTP API](reference/http.md).

Локально без Docker:

```bash
cp .env.example .env
python3 -m pip install -r backend/requirements-dev.txt
make lint
make test
```

Весь стек: `./deploy.sh`. LanguageTool в этом случае всё равно нужен как контейнер или внешний `LANGUAGETOOL_URL`.

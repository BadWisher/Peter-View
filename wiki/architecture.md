# Архитектура

Три контейнера. С хоста виден только nginx.

```
браузер
  → frontend (nginx) : PROOFREADER_PORT
       → /           статика SPA (hash-роутер)
       → /api        FastAPI в backend
  LanguageTool        только из Docker-сети, :8010
  LLM                 только если админ задал URL
```

Backend: один процесс FastAPI. Vale и pymorphy3 крутятся там же. LanguageTool вынесен, потому что Java и полтора гигабайта.

Интерфейс: `frontend/public/js/`, по файлу на раздел (`check.js`, `guides.js`, …), без сборщика. Строки оболочки: `frontend/public/i18n/ru.json` и `en.json`. Язык по умолчанию русский.

Пользователи: `data/users.json`. Журнал: `data/audit.jsonl` (вход, роли, настройки, запись гайда). Гайды: `data/styleguides`.

Конфиг разделов отдаётся фронту с `/api/config`. Middleware на выключенных разделах отвечает 404.

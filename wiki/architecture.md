# Архитектура

Один процесс FastAPI, ванильный hash-SPA, LanguageTool рядом в Compose.

```
браузер → nginx (frontend) → /api → FastAPI
                              ↘ LanguageTool
                              ↘ LLM по желанию администратора
```

Интерфейс: `frontend/public/js/`, по файлу на раздел, без фреймворка. Словарь строк: `frontend/public/i18n/`.

Пользователи: `data/users.json`. Журнал действий: `data/audit.jsonl`.

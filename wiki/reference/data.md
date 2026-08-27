# Хранилище

Том Docker `backend-data` смонтирован в контейнере backend как `/app/data`. Образы этого каталога не содержат. `make backup` упаковывает его в tar в `./backups` на хосте.

## Файлы и базы

| Путь в контейнере | Формат | Содержание |
|---|---|---|
| `/app/data/users.json` | JSON | Логины, хеш bcrypt, роль, признак OIDC |
| `/app/data/user_prefs.json` | JSON | Выбранный Style Guide пользователя |
| `/app/data/llm_settings.json` | JSON | Адрес модели и эмбеддингов, ключи. Перекрывает `.env` |
| `/app/data/styleguides/<id>.yaml` | YAML | Правила и словарь гайда |
| `/app/data/jobs.db` | SQLite | Задачи вычитки: статус, стадия, готовый отчёт |
| `/app/data/stats.db` | SQLite | История проверок, счётчики правил и токенов |
| `/app/data/watch.db` | SQLite | Группы и страницы наблюдения, снимки |
| `/app/data/api_specs.json` | JSON | Связки OpenAPI |
| `/app/data/screenshot_templates.json` | JSON | Шаблоны ширины редактора |
| `/app/data/audit.jsonl` | JSONL | Журнал действий администратора |
| `/app/data/rules.json` | JSON | Пользовательские regex-правила (HTTP `/api/rules`) |
| `/app/data/repo/folders.json` | JSON | Дерево папок репозитория |
| `/app/data/repo/docs/<id>.json` | JSON | Карточка документа и версии |
| `/app/data/repo/blobs/<id>/<n>.bin` | байты | Файл версии |

Встроенный гайд сидится из образа: `/app/styleguide/rules.yaml`. Копия на томе живёт в `styleguides/default.yaml` и не удаляется.

Репозиторий документов общий для всех пользователей. Потолок файла репозитория: `REPO_MAX_FILE_BYTES`, по умолчанию 25 МБ (это не лимит вычитки в 50 МБ).

## Что не на томе

Сессии входа: словарь в памяти процесса. Рестарт backend сбрасывает cookie.

Живой SSE-текст воркеров: только память, в SQLite не пишется. Готовый отчёт в `jobs.db` остаётся.

LanguageTool своего тома не имеет: словари внутри образа JVM.

## Снимки

`BACKUP_DIR` в контейнере, по умолчанию `/app/backups`, на хосте `./backups`. `BACKUP_KEEP` - сколько tar хранить, по умолчанию 7.

Восстановление: остановить стек, распаковать tar так, чтобы снова получился каталог `data` внутри тома, запустить стек.

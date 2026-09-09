# Модель данных

Все персистентные данные в `/app/data` (том `backend-data`). Три SQLite-базы, горстка JSON-файлов, два каталога. Форматы выбраны по принципу «нет внешний зависимости»: приложение читает/пишет само, миграций нет, совместимость назад обеспечивает код.

## Каталог

```text
/app/data
├── users.json                  аккаунты
├── llm_settings.json           настройки модели (0600, содержит ключи)
├── rules.json                  глобальные пользовательские регулярки
├── user_prefs.json             выбор активного гайда по пользователям
├── screenshot_templates.json   шаблоны ширины скриншотов
├── audit.jsonl                 журнал аудита (последние 2000 строк)
├── jobs.db                     задачи LLM-вычитки
├── stats.db                    токены, срабатывания правил, история, кэш LLM
├── watch.db                    мониторинг (+ watch.db.key ключ обфускации)
├── styleguides/                гайды: <id>/guide.json (+ <id>/index/)
└── repo/                       документный репозиторий
```

## JSON-файлы

| Файл | Форма | Примечание |
|---|---|---|
| `users.json` | `{username: {password_hash, role, source}}` | bcrypt-хэши; при пустом файле сервис сидит `admin/admin` |
| `llm_settings.json` | плоский dict полей из `SPEC` | пишется с umask 0077 + chmod 600; читается env-дефолтами при отсутствии |
| `rules.json` | `[{id, pattern, message, severity}]` | id uuid, валидация паттерна при записи |
| `user_prefs.json` | `{username: {styleguide_id}}` | только выбор гайда, ничего больше |
| `screenshot_templates.json` | `[{id, name, width}]` | глобальные, не по пользователям |
| `audit.jsonl` | строки JSON: ts, actor, action, detail | append-only, обрезается до 2000 строк |

## jobs.db

Одна таблица `jobs(id, source, status, stage, report, error, created_at)`. `report` целиком JSON отчёта воткнут в TEXT колонку. Смысл: готовые отчёты переживают рестарт, незавершённые при старте помечаются `status=error` («Прервано рестартом сервера»). Стрим-буферы воркеров в БД не пишутся (только память, до `LLM_STREAM_BLOCK_CAP` знаков на блок). TTL в памяти 1 час (`JOB_TTL_SECONDS`) живые задачи; в БД записи не удаляются (растёт до ручного vacuum, при переполнении диска это кандидат на чистку).

## stats.db

| Таблица | Содержимое |
|---|---|
| `token_usage` | ts, user, job_id, prompt/completion/cached tokens, worker |
| `rule_hits` | (user, rule_id) PK, description, count, last_ts база «Аналитики» |
| `check_history` | id, user, ts, source, гайд, счётчики, `report` целиком; 50 строк на пользователя, старые удаляются |
| `doc_views` | (user, doc_id) PK, ts отметки «видел» в репозитории |
| `llm_cache` | key=хэш промпта, response=JSON, ts персистентный кэш ответов модели |

## watch.db

`groups` (авторизация, пароли XOR-обфусцированы), `pages`, `snapshots` (текст до `WATCH_TEXT_CAP`, DOM-JSON до `WATCH_DOM_CAP`, findings, флаг current), `meta`. Держится 14 снимков на страницу, дальше хвост режется.

## styleguides/

Каждый гайд директория `<id>/guide.json`: meta, rules[], lexicon{forbidden[], allowed[]}. Встроенный `default` сидится из `backend/styleguide/rules.yaml` (read-only bind-mount), удалить его нельзя. Соседний `<id>/index/` служебный кэш RAG не трогаем, индексы живут в памяти и перестраиваются по content hash.

## repo/

Файловая иерархия: папки директории с `folder.json`, документы `<doc-id>/` с `doc.json` (метаданные, версии, seen-отметки) и самими файлами версий `1.docx`, `2.docx`, ... Архивная папка отдельная, документы в неё переезжают физически. Id папок/документов regex-валидируются против path traversal.

## Консистентность и бэкап

Все файлы и базы пишет один процесс (Lock'и на JSON-файлах, SQLite в дефолтном rollback-journal режиме). Снимок всего `data/` через `tar` достаточен для восстановления: journal SQLite откатывается сам при следующем открытии после краша. Бэкап и восстановление описаны [в DevOps-разделе](../ops/backup.md).

## Дальше

- [Стек](../ops/stack.md) где том монтируется.
- [Конвейер](pipeline.md) откуда берётся `report` в jobs.db и stats.db.

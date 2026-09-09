# Подсистемы: документы, спецификации, мониторинг, скриншоты

Четыре модуля живут по краям ядра и включают свои API только под feature-флагами. Здесь как они устроены, пользовательская часть в разделе [Пользователям](../users/sections.md).

## Репозиторий документов (`llm/repo_store.py`, флаг `FEATURE_DOCUMENTS`)

Хранилище проверяемых файлов с иерархией папок и версиями. Всё на файловой системе в `data/repo/`, метаданные в JSON-файлах того же дерева (БД не заводится).

- Каталог `data/repo/`: папки как директории (id путь, защищён regex от `../`), документы поддоном id с версиями `<doc>/<n>.<ext>` и метаданными.
- Метаданные: название, note, jira, автор, created_at, версия, kind (`upload`/`review`), per-user `seen` (отметка «новое»).
- Лимит файла `REPO_MAX_FILE_BYTES` (25 MiB). Суммарный размер не лимитирован следите за диском.
- Автоархив: фоновый цикл раз в 6 ч (`routers/background.py`) переносит в архив документы без обращений `REPO_ARCHIVE_AFTER_DAYS` (90) дней.
- Поиск `GET /api/repo/search?q=` простой подстрокой по именам, без индекса.
- Скачивание версии прямой GET с двойным `Content-Disposition` (ASCII + UTF-8 `filename*`) под русские имена файлов.

## OpenAPI-связки (`llm/api_specs.py`, `api_review.py`, `openapi_fields.py`, флаг `FEATURE_API`)

Связка скрепляет два документа из репозитория: RU- и EN-версию одной OpenAPI-спеки.

- `api_specs.py` парсит YAML (safe_load), вытаскивает «сегменты» именованные фрагменты: описание пути/операции/схемы с русским и английским текстом пары. Сегмент ключ `path + метод + поле` (или имя схемы/поля). Поля `description`, `summary`, имена параметров и т. п.
- `openapi_fields.py` сравнение: обход дерева RU/EN, нахождение расхождений (поле есть в одной и отсутствует в другой, разное описание при пустом переводе, термины-синонимы рядом).
- Версионирование: `has_previous` связка помнит предыдущую пару версий; `diff` отдаёт изменённые пути с русским и английским.
- ИИ-режимы (`api_review.py`): `ai-review` и `translate` не свои воркеры, а generic-задача через `llm_jobs.submit_task` (тот же jobs-механизм, поллинг `/api/jobs/{id}`): модель получает изменённые сегменты диффа, возвращает замечания/переводы. Отдельного конвейера нет.
- Выгрузка правок: `POST .../download` с `edits: {сегмент: новый_текст}` применяет точечные замены к последней YAML, отдаёт `<base>_edited.yaml`. Это текстовые правки, не переформатирование спеки.

## Мониторинг страниц (`llm/watch_store.py`, `watch_run.py`, `watch_dom.py`, `watch_render.py`, флаг `FEATURE_WATCH`)

- **Хранение.** SQLite `data/watch.db`: группы (name, auth_kind `none|form|basic`, login_url, username, пароль, имена полей формы), страницы (group_id, url, title, enabled), снимки (page_id, ts, text, dom, findings_json, is_current). Снимков на страницу `WATCH_SNAPSHOT_KEEP` (14). Пароли и снимки обфусцированы HMAC-keystream XOR по ключу `PROOFREADER_SECRET` (см. [секьюрити](security.md)).
- **Обход (`watch_run.py`).** Одна страница: `safe_request` из `net_guard` (SSRF-guard тот же, что у вычитки по URL). Форма-логин: `safe_post` на login_url с полем/паролем, cookie подхватывается в session; basic: заголовок Authorization. Текст извлекается `watch_dom.py` (lxml: извлечение видимого текста + структура элементов с css-path атрибутами). Лимиты `WATCH_TEXT_CAP`/`WATCH_DOM_CAP`.
- **Дифф.** Текущий снимок против прошлого (`previous`): текстовый (раздел на строки и diff-хунки) и структурный (UI-события: текст/добавление/удаление/сдвиг/смена тега/атрибута по `data-pvwatch-path`). `ui`-события, покрытые текстовыми хунками, дедуплицируются. Из хунков и событий фронт later собирает русские фразы (логику фраз `watchUiSentence` смотри в [карте фронтенда](frontend-map.md), сервер отдаёт сырые данные).
- **Снимок-копия (`watch_render.py`).** Отрисовка сохранённой страницы для iframe (`.../copy`) с подсветкой по `data-pvwatch-path`. PNG-скриншот (`.../shot`) через Playwright + headless Chromium (`PROOFREADER_WATCH_RENDER_TIMEOUT` 25 с, `..._SETTLE_MS` 1200 мс ожидания устоятия). Chromium ставится в Dockerfile; без него 503.
- **Расписание.** Фоновый обход всех групп в `PROOFREADER_WATCH_HOUR` (4 утра) (`background.start_watch_daily`), плюс ручной `POST .../run`. Одиночный in-process lock `_watch_running`: параллельно обход не идёт (вторая команда вернёт `{"status":"running"}`).

## Скриншоты (`llm/shot_templates.py`, флаг `FEATURE_SCREENSHOTS`)

Тонкий модуль: сервер хранит только шаблоны ширины (`data/screenshot_templates.json`: name, width; дефолты 800/1200, валидация 50–4000 px). Сама обработка картинки (crop/redact/paint) клиентская, в canvas фронтенда. На сервер не уходит ни один пиксель.

## Дальше

- [SSRF-защита](security.md): net_guard в обходах и загрузках.
- [Модель данных](data-model.md): где физически что лежит.
- [HTTP API](../dev/api.md): контракты эндпоинтов подсистем.

# Карта фронтенда

Структурный справочник SPA: маршруты, модули, зависимости и точки расширения. Как писать код по конвенциям [Фронтенд: код](../dev/frontend.md); что отдаёт сервер [HTTP API](../dev/api.md).

## Каркас страницы

`index.html` статический скелет на 58 строк. Порядок загрузки: `theme-boot.js` (classic script, до отрисовки ставит `data-theme` из localStorage) → `tokens.css` и `style.css` (версии `?v=48`/`?v=52` руками) → `js/app.js` как `type="module"`, остальные модули доезжают по import-графу. Внутри HTML три контейнера (`#app`, `#overlay-root`, `#toast-root`) и SVG-спрайт 32 иконок; шаблонов во HTML нет, вся разметка собирается из JS.

## Модули и зависимости

```text
app.js ──→ router.js ──→ каждый renderX()
   │            │              │
   │            │              ▼
   │            └──────→ shared.js ──→ i18n.js
   │                        ▲   ▲
   │        hooks (bindShell, renderApp)
   └──── назначает hooks ←───┘
auth.js, check.js, documents.js, guides.js, health.js, history.js,
insights.js, settings.js, users.js, watch.js, screenshots.js, api-specs.js
```

| Модуль | Строк | Ответственность |
|---|---|---|
| `shared.js` | 956 | `state`, `api()`, shell (сайдбар+топбар), модалка, тосты, тема, health-бейдж; ~480 из них мок `previewApi` для демо-режима |
| `watch.js` | 865 | мониторинг: список групп, композер, страница, дифф, копия в iframe, слияние хунков и UI-событий в фразы |
| `check.js` | 815 | форма проверки, SSE-стрим воркеров, экран разбора, подсветка, экспорт |
| `guides.js` | 452 | гайды: список, табы правил/лексикона, CRUD, извлечение из DOCX, merge-движок слияния гайда |
| `api-specs.js` | 286 | раздел API: пары RU/EN, сегменты с правками, consistency, diff, translate/review |
| `documents.js` | 217 | библиотека папок и версий, загрузка drag&drop, архив |
| `screenshots.js` | 216 | canvas-редактор: crop/redact/picker, undo на 6 шагов, экспорт с шириной из шаблона |
| `auth.js` | 115 | логин, logout, смена пароля, `loadInitialData` |
| `app.js` | 77 | bootstrap, горячие клавиши `j/k/h`, `hashchange` |
| остальные: `settings` 60, `shell` 51, `users` 46, `router` 44, `insights` 42, `i18n` 37, `health` 35, `history` 27 | | админ-формы, связка shell-событий, таблицы |

Замкнутые циклы импортов (`shared` ↔ `check`/`watch`/`auth`) разорваны объектом `hooks`: `shared.js` вызывает `hooks.bindShell`/`hooks.renderApp`, а назначает их `app.js` при старте.

## Таблица маршрутов

Hash-роуты (`#/`), разбор в `currentRoute()`, диспетчеризация в `router.js`:

| Хеш | Рендер | Гвард |
|---|---|---|
| `#/check` | `check.renderCheck` | вход |
| `#/review` | `check.renderReview` | вход (в навигации скрыт, активен как «Вычитка») |
| `#/guides` | `guides.renderGuides` | вход |
| `#/history`, `#/insights` | `history`, `insights` | вход |
| `#/documents` | `documents.renderDocuments` | вход + `FEATURE_DOCUMENTS` |
| `#/watch[/gid[/pid]]` | `watch.renderWatch` | вход + `FEATURE_WATCH` |
| `#/api` | `api-specs.renderApiSpecs` | вход + `FEATURE_API` |
| `#/screenshots` | `screenshots.renderScreenshots` | вход + `FEATURE_SCREENSHOTS` |
| `#/settings`, `#/users`, `#/health` | соответствующие | вход + роль admin |

Непройденный гвард `history.replaceState` на `#/check`. Аргументы watch читаются из сегментов хеша. Неизвестный маршрут считается `check`.

## Экран ↔ эндпоинты

| Экран | Читает | Пишет |
|---|---|---|
| логин | `GET /api/config` | `POST /api/auth/login`, `GET /api/auth/oidc/start` |
| bootstrap | `GET /api/auth/me`, `/api/styleguides`, `/api/config` | |
| вычитка | | `POST /api/jobs`, `GET /api/jobs/{id}[/stream|/report]` |
| разбор | `report.blocks/issues` | `POST /api/report-issues` (xlsx) |
| гайды | `GET /api/styleguides[/id][/index-status]` | select/PUT/POST/DELETE, extract + poll |
| история | `GET /api/checks/history[/id]` | открывает сохранённый report в разборе |
| аналитика | `GET /api/checks/insights` | |
| пользователи | `GET /api/users` | POST/DELETE |
| настройки | `GET /api/settings` | `PUT /api/settings`, `POST /api/settings/test` |
| система | `GET /api/health/full` | только refresh (кэш бейджа 60 с) |
| документы | `GET /api/repo/folders|search|archived|documents/{id}` | folders/documents CRUD, versions, archive |
| API-раздел | `GET /api/api-specs.../segments|consistency|diff` | CRUD, translate/ai-review через jobs, download |
| мониторинг | `GET /api/watch/groups.../pages.../diff|copy|history` | CRUD, run, seen |
| скриншоты | `GET /api/screenshot-templates` | POST/DELETE (редактор целиком клиентский) |

## Точки расширения

- Новый экран: три строки (модуль c `renderX`, импорт в `router.js`, пункт в `navItems`/`routeMeta`) плюс флаг в `FEATURE_ROUTES`, если отключаемый. Пошагово [Фронтенд](../dev/frontend.md#как-добавить-раздел).
- Новый ответ сервера: алиасы полей разбирает `normalizedIssues()` в `check.js:555` новая форма замечания добавляется там, а не на месте использования.
- Демо-режим: каждая новая ручка требует кейс в `previewApi` (`shared.js`), иначе `?preview=1` падает на этом экране.

## Известные дефекты карты

Небольшие расхождения, о которых знают и которые ловлятся глазами при правке: `guides.js` в обработчике ошибок использует `overlayRoot`/`app` без импорта (крэш на error-пути); `documents.js` в preview-ветке зовёт неимпортированный `previewApi`; в спрайте нет `icon-copy`, на который ссылается панель копии watch; `icon-filter`/`icon-more`/`icon-star` объявлены, но не используются.

## Дальше

- [Карта кода](../dev/code-map.md) где лежит весь остальной репозиторий.
- [Безопасность](security.md) почему CSP и sandbox рамка копии.
- [Проектные решения](decisions.md) почему SPA без фреймворка и полная перерисовка.

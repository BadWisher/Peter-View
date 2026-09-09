# Карта кода

Расположение всего, что есть в репозитории, и ответственность каждого куска. Страница справочная: здесь нет объяснений, как что работает, только «файл X за что отвечает». За устройством [Архитектура](../arch/overview.md).

```
Peter-View/
├── docker-compose.yml          три сервиса, тома, healthchecks
├── docker-compose.prod.yml     override: образы из GHCR вместо сборки
├── docker-compose.corp-proxy.yml  override: трафик через корп-прокси (socat-мост)
├── deploy.sh                   копия .env, сборка, up, ожидание фронта, адреса
├── Makefile                    deploy|test|lint|regression|ci-local|backup|...
├── .env.example                все переменные с комментариями
├── pyproject.toml              конфиг pytest: pythonpath=backend, testpaths
├── mkdocs.yml                  сборщик вики: docs_dir=wiki, site_dir=docs/wiki
├── CHANGELOG.md                релизы (Keep a Changelog)
├── README.md, SECURITY.md, LICENSE, NOTICE, ...
│
├── backend/                    всё серверное (python 3.12)
│   ├── Dockerfile              python:3.12-slim + vale 3.9.1 + playwright chromium
│   ├── entrypoint.sh           chmod томов, gosu appuser
│   ├── requirements.txt        21 пакет; -dev: pytest, pytest-asyncio, ruff
│   ├── app/
│   │   ├── main.py             сборка FastAPI: 15 роутеров, 3 middleware, startup-циклы
│   │   ├── auth.py             сессии, роли admin|editor, bcrypt, users.json
│   │   ├── oidc.py             Authorization Code: discovery, exchange, роль из групп
│   │   ├── features.py         4 флага разделов из env FEATURE_*
│   │   ├── checker.py          оркестратор 3 детерминированных движков + дедуп
│   │   ├── lt_client.py        клиент LanguageTool, ~8 параллельных, фильтры FP
│   │   ├── vale_runner.py      Vale subprocess --output JSON, постфильтры
│   │   ├── custom_checks.py    5 морфологических проверок (pymorphy3 + razdel)
│   │   ├── extractors.py       docx/html/md/txt в текст, zip-bomb guard
│   │   ├── crawler.py          BFS по сайту, robots.txt, до 200 страниц
│   │   ├── net_guard.py        SSRF-защита: проверка IP, ручные редиректы, лимит тела
│   │   ├── style_guide_registry.py  56 встроенных правил + слой LanguageTool (817 строк)
│   │   ├── report.py           xlsx через openpyxl
│   │   ├── backups.py          tar.gz всего /app/data, ротация 7 снимков
│   │   ├── audit.py            JSONL-журнал действий (до 2000 записей)
│   │   ├── regression_checks.py  44 кейса «правило должно/не должно сработать»
│   │   ├── site_audit.py       CLI: аудит сайта целиком в JSON
│   │   ├── routers/            HTTP-слой, 89 маршрутов (обход по одному на домен)
│   │   └── llm/                вычитка моделью: 25 модулей, промпты, RAG
│   ├── vale/styles/RuStyleGuide/   48 yml-стилей Vale
│   ├── styleguide/rules.yaml       56 правил гайда (v3), источник истины для LLM
│   ├── eval/                       20 эталонных кейсов + run_eval.py против живой модели
│   └── tests/                      10 pytest-файлов, 103 теста
│
├── frontend/
│   ├── Dockerfile              nginx:alpine (по digest), копия public/
│   ├── nginx.conf              159 строк: CSP, proxy /api/, SSE без буфера, копия страниц
│   └── public/                 SPA: index.html (58 строк, SVG-спрайт 32 иконок)
│       ├── js/                 17 ES-модулей, 4306 строк
│       ├── i18n/               ru.json, en.json (44 ключа на файл, покрытие частичное)
│       ├── tokens.css          12 @property-переменных, светлая и тёмная темы
│       ├── theme-boot.js       антиFOUC: читает pv-theme до первой отрисовки
│       ├── style.css           4513 строк всей вёрстки, одним файлом
│       └── fonts/              Golos Text, JetBrains Mono (woff2, subsets)
│
├── docs/                       публикация GitHub Pages
│   ├── wiki/                   собранная вики (mkdocs build, закоммичен)
│   └── preview/                интерактивное демо UI (?preview=1, mock API в shared.js)
├── landing/                    index.html лендинга для корня Pages
├── wiki/                       исходники этой вики (mkdocs docs_dir)
├── examples/openapi/           парная RU/EN спека для демонстрации раздела «API»
└── .github/workflows/          ci.yml | pages.yml | publish.yml
```

## Как навигировать по бэкенду

Три слоя, и путь запроса почти всегда одного вида:

1. `routers/*` проверяет cookie-роль и флаг раздела, режет вход по лимитам, вызывает следующий слой.
2. Либо `checker.py` с его движками (синхронная проверка детерминированно), либо `llm/pipeline_v2.py` (долгая задача с очередью через `llm/jobs.py`).
3. Хранилище: всё пишет в файлы и SQLite под `/app/data`, кто владеет чем [Модель данных](../arch/data-model.md).

Держите в уме: `styleguide/rules.yaml` и `style_guide_registry.py` дублируют друг друга намеренно (первый для модели, второй для движков и UI), и тест `test_styleguide_consistency.py` не даёт им разъезжаться.

## Как навигировать по фронту

`app.js` загружается из `index.html`, инициализирует i18n, тянет `/api/auth/me`, и `router.js` по хешу вызывает нужный `renderX()`. Каждый экран своя ES-модуль; общие куски (shell, toast, модалка, `api()`) в `shared.js`. Полная карта роутов и связей модулей [Карта фронтенда](../arch/frontend-map.md).

## Дальше

- [Бэкенд](backend.md) конвенции, добавление движка и маршрута.
- [Фронтенд](frontend.md) конвенции, добавление раздела.
- [Правила гайда](guides-rules.md) форматы правил во всех трёх слоях.
- [Тесты](tests.md) что и как прогонять.
- [HTTP API](api.md) справочник маршрутов.

#!/usr/bin/env python3
"""Генератор SVG-диаграмм для вики. Запуск: python3 scripts/gen_diagrams.py

Диаграммы:
  overview.svg    схема контейнеров и модулей backend
  frontend-graph.svg  граф ES-модулей фронтенда
  query-path.svg  путь запроса в бэкенде
  data-dir.svg    содержимое каталога /app/data
"""
from pathlib import Path

FONT = "font-family=\"'Segoe UI', 'Liberation Sans', sans-serif\""
OUT = Path(__file__).resolve().parent.parent / 'wiki' / 'diagrams'
OUT.mkdir(exist_ok=True)

TEAL = '#013b32'
MINT = '#eef5f3'
MINT_LINE = '#8fb3ac'
SAND = '#f5f1e6'
SAND_LINE = '#b39b5e'
TXT = '#013b32'
SUB = '#25443f'
CAP = '#4d635e'
LINE = '#3a5f59'


def header(w, h, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="100%" {FONT} font-size="14" role="img" aria-label="{label}">\n')


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def box(x, y, w, h, lines, kind='box'):
    fill, stroke = {
        'box': ('#ffffff', TEAL),
        'grp': (MINT, MINT_LINE),
        'ext': (SAND, SAND_LINE),
    }[kind]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" '
           f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>']
    y_text = y + 24
    for i, (text, cls) in enumerate(lines):
        weight = ' font-weight="600"' if cls == 't' else ''
        size = {'t': 14.5, 'm': 12.5, 'cap': 11.5}.get(cls, 13)
        color = {'t': TXT, 'm': SUB, 'cap': CAP}.get(cls, SUB)
        out.append(f'<text x="{x+14}" y="{y_text}" fill="{color}" '
                   f'font-size="{size}"{weight}>{esc(text)}</text>')
        y_text += size + 5.5
    return '\n'.join(out)


def arrow(x1, y1, x2, y2, label=None, dashed=False, color=LINE, width=1.4):
    dash = ' stroke-dasharray="5,4"' if dashed else ''
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
           f'stroke-width="{width}"{dash} marker-end="url(#ar-{color[1:]})"/>']
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out.append(f'<text x="{mx+8}" y="{my+4}" fill="{CAP}" font-size="11.5">{esc(label)}</text>')
    return '\n'.join(out)


def defs():
    colors = {LINE, TEAL}
    out = ['<defs>']
    for c in colors:
        out.append(f'<marker id="ar-{c[1:]}" markerWidth="9" markerHeight="9" '
                   f'refX="7" refY="3.2" orient="auto" markerUnits="userSpaceOnUse">'
                   f'<path d="M0,0 L7,3.2 L0,6.4 Z" fill="{c}"/></marker>')
    out.append('</defs>')
    return '\n'.join(out)


# --- 1. Схема контейнеров и модулей backend -------------------------------
def overview():
    W, H = 760, 560
    parts = [header(W, H, 'Схема контейнеров Peter View и модулей backend'), defs()]

    parts.append(box(24, 16, 320, 52, [('Браузер', 't'), ('SPA на vanilla JS, без сборки', 'm')]))
    parts.append(arrow(184, 68, 184, 96, label='http(s)', color=TEAL))
    parts.append(box(24, 96, 320, 70, [
        ('Frontend-контейнер: nginx', 't'),
        ('раздает статику интерфейса', 'm'),
        ('обратный прокси /api/ на backend:8000', 'm')]))
    parts.append(arrow(184, 166, 184, 194, color=TEAL))
    parts.append(box(24, 194, 320, 52, [('Backend: FastAPI', 't'), ('один процесс uvicorn, asyncio', 'm')]))

    parts.append(box(380, 16, 356, 372, [], 'grp'))
    parts.append(f'<text x="394" y="38" fill="{TXT}" font-size="14.5" font-weight="600">Модули backend</text>')
    y = 50
    for title, sub in [
        ('routers/', 'HTTP-слой: маршруты, роли, флаги разделов'),
        ('checker.py', 'фасад детерминированных движков и дедупликация'),
    ]:
        parts.append(box(394, y, 328, 52, [(title, 't'), (sub, 'm')]))
        y += 60
    for title, sub in [
        ('lt_client.py', 'клиент контейнера LanguageTool'),
        ('vale_runner.py', 'подпроцесс Vale внутри backend'),
        ('custom_checks.py', 'морфология на pymorphy3 и razdel'),
        ('style_guide_registry.py', 'реестр правил + styleguide/rules.yaml'),
    ]:
        parts.append(box(410, y, 312, 40, [(f'{title} {sub}', 'm')], 'box'))
        y += 46
    y += 8
    parts.append(box(394, y, 328, 118, [
        ('llm/ конвейер вычитки моделью', 't'),
        ('documents.py разбор входов в блоки', 'm'),
        ('pipeline_v2.py планировщик стадий', 'm'),
        ('workers.py, evidence.py, client.py, jobs.py', 'm'),
    ], 'grp'))
    parts.append(arrow(344, 220, 378, 220, color=TEAL))

    parts.append(box(24, 268, 320, 54, [
        ('Прикладные подсистемы', 't'),
        ('repo_store, api_specs, watch_*, shot_templates', 'm')], 'grp'))
    parts.append(arrow(184, 246, 184, 266, color=TEAL))
    parts.append(box(24, 338, 320, 54, [
        ('Данные', 't'),
        ('/app/data (JSON + SQLite) на томе backend-data', 'm')], 'grp'))
    parts.append(arrow(184, 322, 184, 336, color=TEAL))

    parts.append(box(24, 440, 320, 70, [
        ('LanguageTool-контейнер', 't'),
        ('JVM, русская модель, только сеть docker', 'm'),
        ('доступен backend по внутреннему адресу', 'cap')], 'box'))
    parts.append('<path d="M458,388 L458,414 L184,414 L184,438" fill="none" '
                 f'stroke="{LINE}" stroke-width="1.4" stroke-dasharray="5,4" '
                 'marker-end="url(#ar-3a5f59)"/>')
    parts.append(f'<text x="200" y="410" fill="{CAP}" font-size="11.5">запросы lt_client к движку</text>')

    parts.append(box(380, 440, 356, 70, [
        ('Внешние зависимости', 't'),
        ('endpoint модели (OpenAI-совместимый),', 'm'),
        ('провайдер OIDC (задается администратором)', 'm')], 'ext'))
    parts.append(arrow(558, 392, 558, 438, dashed=True))
    parts.append(f'<text x="566" y="420" fill="{CAP}" font-size="11.5">HTTP-вызовы модели и OIDC</text>')

    parts.append('</svg>')
    (OUT / 'overview.svg').write_text('\n'.join(parts), encoding='utf8')


# --- 2. Граф ES-модулей фронтенда ----------------------------------------
def frontend_graph():
    W, H = 760, 320
    parts = [header(W, H, 'Граф зависимостей ES-модулей фронтенда'), defs()]

    def mod(x, y, title, sub, kind='box', w=150):
        return box(x, y, w, 46, [(title, 't'), (sub, 'cap')], kind)

    parts.append(mod(24, 24, 'index.html', 'каркас, SVG-спрайт', 'grp', 160))
    parts.append(mod(230, 24, 'app.js', 'точка входа', 'box', 150))
    parts.append(mod(430, 24, 'router.js', 'хеш-роутер', 'box', 150))
    parts.append(mod(610, 24, 'renderX()', 'рендер разделов', 'box', 130))

    parts.append(mod(230, 130, 'shared.js', 'state, api(), оболочка, тосты', 'box', 190))
    parts.append(mod(490, 130, 'i18n.js', 'словари ru и en', 'box', 150))

    parts.append('<rect x="24" y="236" width="716" height="66" rx="8" '
                 f'fill="{MINT}" stroke="{MINT_LINE}" stroke-width="1.4"/>')
    parts.append(f'<text x="38" y="260" fill="{TXT}" font-size="14.5" font-weight="600">12 модулей разделов</text>')
    parts.append(f'<text x="38" y="278" fill="{CAP}" font-size="11.5">auth, check, documents, guides, health, history,</text>')
    parts.append(f'<text x="38" y="294" fill="{CAP}" font-size="11.5">insights, settings, users, watch, screenshots, api-specs</text>')

    parts.append(arrow(184, 47, 228, 47, color=TEAL))
    parts.append(arrow(380, 47, 428, 47, color=TEAL))
    parts.append(arrow(580, 47, 608, 47, color=TEAL))
    parts.append(arrow(505, 70, 390, 128, color=LINE))
    parts.append(f'<text x="446" y="102" fill="{CAP}" font-size="11.5">ответы сервера, оболочка</text>')
    parts.append(arrow(420, 153, 488, 153, color=LINE))
    parts.append(arrow(305, 70, 305, 128, color=TEAL))
    parts.append(f'<text x="313" y="100" fill="{CAP}" font-size="11.5">назначает хуки bindShell, renderApp</text>')
    parts.append(arrow(255, 234, 255, 178, color=LINE))
    parts.append(f'<text x="263" y="212" fill="{CAP}" font-size="11.5">используют state и api()</text>')
    parts.append(arrow(675, 70, 675, 232, color=LINE))
    parts.append(f'<text x="670" y="212" fill="{CAP}" font-size="11.5" text-anchor="end">роутер вызывает</text>')

    parts.append('</svg>')
    (OUT / 'frontend-graph.svg').write_text('\n'.join(parts), encoding='utf8')


# --- 3. Путь запроса в бэкенде -------------------------------------------
def query_path():
    W, H = 760, 340
    parts = [header(W, H, 'Путь запроса через слои backend'), defs()]

    parts.append(box(24, 24, 160, 56, [('браузер', 't'), ('отправка текста,', 'm'), ('получение отчета', 'cap')]))
    parts.append(box(230, 24, 160, 56, [('nginx', 't'), ('статика и', 'm'), ('прокси /api/', 'cap')]))
    parts.append(box(436, 24, 170, 56, [('routers/', 't'), ('роль по cookie,', 'm'), ('флаг раздела, лимиты', 'cap')]))
    parts.append(arrow(184, 52, 228, 52, color=TEAL))
    parts.append(arrow(390, 52, 434, 52, color=TEAL))

    parts.append(box(620, 24, 116, 56, [('ответ', 't'), ('отчет, SSE', 'cap')], 'ext'))
    parts.append(arrow(606, 52, 618, 52, color=LINE))

    # two-level elbows from routers down to each executor
    parts.append('<path d="M521,80 L521,106 L250,106 L250,138" fill="none" '
                 f'stroke="{LINE}" stroke-width="1.4" marker-end="url(#ar-3a5f59)"/>')
    parts.append('<path d="M521,80 L521,106 L586,106 L586,138" fill="none" '
                 f'stroke="{LINE}" stroke-width="1.4" marker-end="url(#ar-3a5f59)"/>')
    parts.append(f'<text x="330" y="100" fill="{CAP}" font-size="11.5">короткий путь</text>')
    parts.append(f'<text x="540" y="100" fill="{CAP}" font-size="11.5">долгий путь</text>')

    parts.append(box(120, 140, 260, 78, [
        ('checker.py', 't'),
        ('синхронная проверка тремя', 'm'),
        ('детерминированными движками', 'm')]))
    parts.append(box(436, 140, 300, 78, [
        ('llm/pipeline_v2.py и llm/jobs.py', 't'),
        ('долгая задача с очередью,', 'm'),
        ('стрим прогресса по SSE', 'm')], 'grp'))

    parts.append(box(280, 260, 200, 64, [
        ('Хранилище /app/data', 't'),
        ('JSON и SQLite', 'm')], 'grp'))
    parts.append(arrow(250, 218, 330, 258))
    parts.append(arrow(586, 218, 430, 258))

    parts.append('</svg>')
    (OUT / 'query-path.svg').write_text('\n'.join(parts), encoding='utf8')


# --- 4. Каталог данных ----------------------------------------------------
def data_dir():
    W, H = 760, 330
    parts = [header(W, H, 'Содержимое каталога /app/data'), defs()]
    parts.append(f'<text x="24" y="34" fill="{TXT}" font-size="14.5" font-weight="600">/app/data (том backend-data)</text>')

    left = [
        ('users.json', 'аккаунты'),
        ('llm_settings.json', 'настройки модели, 0600'),
        ('rules.json', 'глобальные регулярки'),
        ('user_prefs.json', 'выбор активного гайда'),
        ('screenshot_templates.json', 'шаблоны ширины'),
        ('audit.jsonl', 'журнал аудита, 2000 строк'),
    ]
    right = [
        ('jobs.db', 'задачи проверки моделью'),
        ('stats.db', 'токены, история, кэш модели'),
        ('watch.db', 'мониторинг (+watch.db.key)'),
        ('styleguides/', 'гайды: <id>/guide.json, index/'),
        ('repo/', 'документный репозиторий'),
    ]

    def item(x, y, name, sub):
        parts.append(box(x, y, 356, 44, [(name, 't'), (sub, 'cap')]))

    y = 52
    for name, sub in left:
        item(24, y, name, sub)
        y += 46
    y = 52
    for name, sub in right:
        item(380, y, name, sub)
        y += 46
    parts.append('</svg>')
    (OUT / 'data-dir.svg').write_text('\n'.join(parts), encoding='utf8')


# --- 5. Дерево репозитория -------------------------------------------------
ROOT = [
    ('docker-compose.yml', 'три сервиса, тома, healthchecks'),
    ('docker-compose.prod.yml', 'override: образы из GHCR вместо сборки'),
    ('docker-compose.corp-proxy.yml', 'override: трафик через корп-прокси (socat-мост)'),
    ('deploy.sh', 'копия .env, сборка, up, ожидание фронта, адреса'),
    ('Makefile', 'deploy, test, lint, regression, ci-local, backup'),
    ('.env.example', 'все переменные с комментариями'),
    ('pyproject.toml', 'конфиг pytest: pythonpath=backend, testpaths'),
    ('mkdocs.yml', 'сборщик вики: docs_dir=wiki, site_dir=docs/wiki'),
    ('CHANGELOG.md', 'релизы в формате Keep a Changelog'),
    ('README.md, SECURITY.md, LICENSE, NOTICE', 'документы сообщества'),
]
BACKEND_TOP = [
    ('Dockerfile', 'python:3.12-slim + vale 3.9.1 + playwright chromium'),
    ('entrypoint.sh', 'chmod томов, gosu appuser'),
    ('requirements.txt', '21 пакет; -dev: pytest, pytest-asyncio, ruff'),
]
APP = [
    ('main.py', 'сборка FastAPI: 15 роутеров, 3 middleware, startup-циклы'),
    ('auth.py', 'сессии, роли admin и editor, bcrypt, users.json'),
    ('oidc.py', 'Authorization Code: discovery, exchange, роль из групп'),
    ('features.py', '4 флага разделов из env FEATURE_*'),
    ('checker.py', 'оркестратор 3 детерминированных движков + дедуп'),
    ('lt_client.py', 'клиент LanguageTool, ~8 параллельных, фильтры FP'),
    ('vale_runner.py', 'Vale подпроцессом с выводом JSON, постфильтры'),
    ('custom_checks.py', '5 морфологических проверок (pymorphy3 + razdel)'),
    ('extractors.py', 'docx, html, md, txt в текст, защита от zip-бомб'),
    ('crawler.py', 'обход сайта в ширину, robots.txt, до 200 страниц'),
    ('net_guard.py', 'SSRF-защита: проверка IP, ручные редиректы, лимит тела'),
    ('style_guide_registry.py', '56 встроенных правил + слой LanguageTool (817 строк)'),
    ('report.py', 'xlsx через openpyxl'),
    ('backups.py', 'tar.gz всего /app/data, ротация 7 снимков'),
    ('audit.py', 'JSONL-журнал действий (до 2000 записей)'),
    ('regression_checks.py', '44 кейса на срабатывание и несрабатывание правил'),
    ('site_audit.py', 'CLI: аудит сайта целиком в JSON'),
    ('routers/', 'HTTP-слой, 89 маршрутов (обход по одному на домен)'),
    ('llm/', 'вычитка моделью: 25 модулей, промпты, RAG'),
]
BACKEND_SUB = [
    ('vale/styles/RuStyleGuide/', '48 yml-стилей Vale'),
    ('styleguide/rules.yaml', '56 правил гайда (v3), источник истины для LLM'),
    ('eval/', '20 эталонных кейсов + run_eval.py против живой модели'),
    ('tests/', '10 pytest-файлов, 103 теста'),
]
FRONTEND = [
    ('Dockerfile', 'nginx:alpine (по digest), копия public/'),
    ('nginx.conf', '159 строк: CSP, прокси /api/, SSE без буфера, копия страниц'),
]
PUBLIC = [
    ('index.html', '58 строк, SVG-спрайт 32 иконок'),
    ('js/', '17 ES-модулей, 4306 строк'),
    ('i18n/', 'ru.json, en.json (44 ключа на файл, покрытие частичное)'),
    ('tokens.css', '12 @property-переменных, светлая и темная темы'),
    ('theme-boot.js', 'антиFOUC: читает pv-theme до первой отрисовки'),
    ('style.css', '4513 строк всей верстки, одним файлом'),
    ('fonts/', 'Golos Text, JetBrains Mono (woff2, subsets)'),
]
DOCS = [
    ('wiki/', 'собранная вики (mkdocs build, закоммичен)'),
    ('preview/', 'интерактивное демо UI (?preview=1, mock API в shared.js)'),
]
MISC = [
    ('landing/', 'index.html лендинга для корня Pages'),
    ('wiki/', 'исходники этой вики (mkdocs docs_dir)'),
    ('examples/openapi/', 'парная RU и EN спека для раздела Спецификации API'),
    ('.github/workflows/', 'ci.yml, pages.yml, publish.yml'),
]


def panel(parts, x, y, title, groups, row_h=20):
    """groups: список (заголовок_подгруппы или None, [(name, note), ...])."""
    rows = sum(len(items) for _, items in groups)
    heads = sum(1 for sub, _ in groups if sub)
    h = 40 + heads * 20 + rows * (row_h + 4) + 6
    parts.append(f'<rect x="{x}" y="{y}" width="712" height="{h}" rx="10" '
                 f'fill="{MINT}" stroke="{MINT_LINE}" stroke-width="1.4"/>')
    parts.append(f'<text x="{x+16}" y="{y+26}" fill="{TXT}" font-size="14.5" '
                 f'font-weight="600" font-family="monospace">{esc(title)}</text>')
    yy = y + 36
    for sub, items in groups:
        if sub:
            parts.append(f'<text x="{x+28}" y="{yy+14}" fill="{TXT}" font-size="12.5" '
                         f'font-weight="600" font-family="monospace">{esc(sub)}</text>')
            yy += 20
        for name, note in items:
            parts.append(f'<text x="{x+44}" y="{yy+14}" fill="{SUB}" font-size="12" '
                         f'font-family="monospace">{esc(name)}</text>')
            parts.append(f'<text x="{x+320}" y="{yy+14}" fill="{CAP}" font-size="11.5">'
                         f'{esc(note)}</text>')
            yy += row_h + 4
    return y + h


def repo_tree():
    H = 40
    parts = [header(760, H, 'Дерево файлов репозитория Peter View'), defs()]
    y = 16
    y = panel(parts, 24, y, 'Peter-View/', [(None, ROOT)]) + 16
    y = panel(parts, 24, y, 'backend/', [
        (None, BACKEND_TOP), ('app/', APP), (None, BACKEND_SUB)]) + 16
    y = panel(parts, 24, y, 'frontend/', [(None, FRONTEND), ('public/', PUBLIC)]) + 16
    y = panel(parts, 24, y, 'docs/ и прочее', [(None, DOCS), (None, MISC)])
    svg = '\n'.join(parts).replace(f'viewBox="0 0 760 {H}"', f'viewBox="0 0 760 {y}"')
    (OUT / 'repo-tree.svg').write_text(svg + '\n</svg>', encoding='utf8')


def tls_path():
    W, H = 760, 120
    parts = [header(W, H, 'Путь запроса от браузера к контейнеру frontend'), defs()]
    parts.append(box(16, 24, 158, 54, [('браузер', 't'), ('адрес сервиса', 'cap')]))
    parts.append(box(238, 24, 240, 54, [('внешний nginx или Caddy', 't'),
                                         ('расшифровка и прокси', 'cap')]))
    parts.append(box(600, 24, 144, 54, [('контейнер frontend', 't'), ('nginx внутри docker', 'cap')]))
    parts.append(arrow(174, 51, 236, 51, color=TEAL))
    parts.append(f'<text x="176" y="40" fill="{CAP}" font-size="11.5">https</text>')
    parts.append(f'<text x="176" y="92" fill="{CAP}" font-size="11.5">порт 443, TLS</text>')
    parts.append(arrow(478, 51, 598, 51, color=TEAL))
    parts.append(f'<text x="482" y="40" fill="{CAP}" font-size="11.5">http, без шифрования</text>')
    parts.append(f'<text x="482" y="92" fill="{CAP}" font-size="11.5">localhost:3080</text>')
    (OUT / 'tls-path.svg').write_text('\n'.join(parts) + '\n</svg>', encoding='utf8')


overview()
frontend_graph()
query_path()
data_dir()
repo_tree()
tls_path()
print('SVG written to', OUT)
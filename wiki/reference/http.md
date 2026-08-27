# HTTP API

Все пути относительно origin nginx, префикс `/api`. Сессия: cookie `proofreader_session` после `POST /api/auth/login` или OIDC. Без сессии - 401.

Схема OpenAPI: `/api/openapi.json`, если `PROOFREADER_DOCS=true`. Иначе Swagger выключен.

Выключенный флаг раздела даёт 404 на соответствующем префиксе.

## Служебные

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/health` | Жив ли процесс backend |
| GET | `/api/health/full` | Диск, модель, эмбеддинги, репозиторий, backup, журнал. Только admin |
| GET | `/api/config` | Флаги разделов, включён ли OIDC |
| GET | `/api` | Краткий указатель |

## Вход и люди

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/auth/login` | Логин и пароль |
| POST | `/api/auth/logout` | Выход |
| GET | `/api/auth/me` | Текущий пользователь |
| POST | `/api/auth/change-password` | Смена своего пароля |
| GET | `/api/auth/oidc/start` | Редирект в IdP |
| GET | `/api/auth/oidc/callback` | Возврат из IdP |
| GET, POST, PATCH, DELETE | `/api/users` | Учётные записи. Пишет только admin |

## Вычитка

Интерфейс «Вычитка» использует jobs. Прямые `/api/check*` - движки без очереди.

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/api/jobs` | Файл, текст или один URL → `job_id` |
| GET | `/api/jobs/{id}` | Статус и стадия |
| GET | `/api/jobs/{id}/stream` | SSE вывода воркеров |
| GET | `/api/jobs/{id}/report` | Готовый отчёт |
| POST | `/api/check` | Файл → замечания движков |
| POST | `/api/check-text` | Текст → замечания движков |
| POST | `/api/check-url` | Обход сайта до 200 страниц, SSE |
| POST | `/api/report` | Проверка файла или текста → xlsx |
| POST | `/api/report-issues` | Готовый список замечаний → xlsx |
| GET | `/api/checks/history` | История |
| GET | `/api/checks/history/{id}` | Сохранённый отчёт |
| GET | `/api/checks/insights` | Аналитика |

Поля формы `POST /api/jobs`: `file` или `text` или `url`, `styleguide_id`, `check_language`, `check_styleguide`, `check_consistency`, `prompt`.

## Style Guide и правила

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/styleguides` | Список |
| GET | `/api/styleguides/current` | Активный |
| GET, PUT, DELETE | `/api/styleguides/{id}` | Один гайд. Пишет admin |
| POST | `/api/styleguides/{id}/select` | «Использовать» |
| POST | `/api/styleguides/extract` | Разбор docx/txt/md |
| GET | `/api/styleguides/extract/{job_id}` | Стадия разбора |
| GET, POST, DELETE | `/api/rules` | Пользовательские regex |

## Настройки модели

| Метод | Путь | Кто |
|---|---|---|
| GET, PUT | `/api/settings` | admin |
| POST | `/api/settings/test` | admin, проверка адресов |

## По флагу

Префиксы пропадают вместе с пунктом меню.

| Флаг | Префикс |
|---|---|
| `FEATURE_DOCUMENTS` | `/api/repo` |
| `FEATURE_API` | `/api/api-specs`, `/api/api-spec-documents` |
| `FEATURE_WATCH` | `/api/watch` |
| `FEATURE_SCREENSHOTS` | `/api/screenshot-templates` |

Репозиторий: папки, загрузка, версии, архив, поиск, скачивание файла версии.

Связка OpenAPI: сегменты, единообразие, diff, перевод, выгрузка YAML.

Наблюдение: группы, страницы, ручной прогон, diff, суточный цикл на backend.

Лимиты: тело запроса 50 МБ (nginx и FastAPI), страница по URL `PROOFREADER_MAX_FETCH_BYTES` (10 МиБ), файл в репозитории `REPO_MAX_FILE_BYTES` (25 МБ).

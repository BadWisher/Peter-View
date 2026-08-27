# Разделы интерфейса

Маршруты задаются hash. Адрес вида `http://localhost:3080/#/check`.

## Всегда на месте

| Раздел | Hash | Кто видит | Что там |
|---|---|---|---|
| Вычитка | `#/check` | все | Источник, параметры проверки, запуск |
| Очередь решений | `#/review` | все, после отчёта | Карточки, фильтры, J/K/H, экспорт xlsx |
| Style Guide | `#/guides` | все | Список гайдов, правила, словарь. Правки: admin |
| История | `#/history` | все | Последние 50 проверок |
| Аналитика | `#/insights` | все | Частые правила по авторам, токены |

![Вычитка](../screenshots/03-check-form.png)

![Очередь решений](../screenshots/02-check.png)

![Style Guide](../screenshots/04-guides.png)

![История](../screenshots/08-history.png)

![Аналитика](../screenshots/05-insights.png)

## Только администратор

| Раздел | Hash | Что там |
|---|---|---|
| Пользователи | `#/users` | Создание, роли, удаление |
| Настройки | `#/settings` | URL модели и эмбеддингов, проверка связи |
| Система | `#/health` | Диск, LLM, эмбеддинги, репозиторий, резервная копия, журнал |

![Пользователи](../screenshots/06-users.png)

![Настройки](../screenshots/07-settings.png)

![Система](../screenshots/09-health.png)

## По флагу

| Раздел | Hash | Флаг | Что там |
|---|---|---|---|
| Документы | `#/documents` | `FEATURE_DOCUMENTS` | Папки, версии, архив, поиск по Jira |
| API | `#/api` | `FEATURE_API` | Связка OpenAPI RU/EN. Учебные файлы: `examples/openapi/library-ru.yaml`, `library-en.yaml` |
| Наблюдение | `#/watch` | `FEATURE_WATCH` | Группы страниц, снимки, отличие. Без флага цикл не стартует |
| Скриншоты | `#/screenshots` | `FEATURE_SCREENSHOTS` | Кадрирование, скрытие областей, шаблоны ширины |

![Документы](../screenshots/10-documents.png)

![API](../screenshots/12-api.png)

![Наблюдение](../screenshots/13-watch.png)

![Скриншоты](../screenshots/14-screenshots.png)

Выключенный раздел пропадает из меню. Запрос к его `/api/...` отвечает 404. Прежний hash перенаправляет в «Вычитку».

На узком экране те же разделы, меню сворачивается.

![Вычитка на узком экране](../screenshots/11-mobile-check.png)

<p align="center">
  <img src="frontend/public/logo.png" width="72" height="72" alt="Peter View">
</p>

<h1 align="center">Peter View</h1>

<p align="center">
  Open source веб-сервис для автоматической вычитки технической документации.</br>
  От техписателя техписателям с любовью.
</p>

<p align="center">
  <a href="https://badwisher.github.io/Peter-View/preview/"><img alt="Превью" height="36" src="https://img.shields.io/badge/Превью-00a88e?style=for-the-badge"></a>
  &emsp;
  <a href="https://badwisher.github.io/Peter-View/wiki/"><img alt="Документация" height="36" src="https://img.shields.io/badge/Документация-013b32?style=for-the-badge"></a>
  &emsp;
  <a href="https://badwisher.github.io/Peter-View/wiki/tutorial/"><img alt="Установка" height="36" src="https://img.shields.io/badge/Установка-013b32?style=for-the-badge"></a>
</p>

**Peter View** — это инструмент для автоматизированной проверки текстов, предназначенный для контроля грамматики, соблюдения корпоративного стиля, гайдлайнов, tone of voice и единообразия терминологии.</br> 
Система спроектирована с упором на конфиденциальность и корпоративную разработку: по умолчанию все проверки выполняются локально, интеграция с ИИ моделями опциональная и доступна с любыми OpenAI API.</br> 
Результатом работы инструмента является структурированный список замечаний, каждое из которых привязано к конкретному фрагменту исходного документа.</br> 

![Список замечаний рядом с текстом документа](docs/screenshots/02-check.png)

## Возможности вычитки

- Peer Review файла (DOCX, TXT, HTML, MD до 50 МБ), страницы по URL или текста в свободном виде.
- Выбор набора гайдлайнов (Style Guide) для нужной целевой аудитории, который будет использоваться при вычитке.
- Импорт, обновление и удобный интерфейс настройки Style Guide.
- Удобный просмотр и обработка результатов вычитки.
- Экспорт в .xlsx.
- История проверок, аналитика частых ошибок и состояния ИИ моделей.
- Ролевая модель, ограничивающая доступ к части настроек определенным пользователям.

<table>
  <tr>
    <td><img src="docs/screenshots/04-guides.png" alt="Style Guide"></td>
    <td><img src="docs/screenshots/06-users.png" alt="Пользователи"></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/07-settings.png" alt="Настройки модели"></td>
    <td><img src="docs/screenshots/08-history.png" alt="История проверок"></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/05-insights.png" alt="Аналитика"></td>
    <td><img src="docs/screenshots/09-health.png" alt="Состояние сервисов"></td>
  </tr>
</table>

## Дополнительные модули

Кроме вычитки, **Peter View** предлагает набор дополнительных функций, которые можно включить/отключить при деплое.
Их активация производится в файле .env без пересборки интерфейса:

- <code>FEATURE_DOCUMENTS=true</code>. Добавляет в интерфейс раздел **Документы** - небольшой репозиторий/хранилище для документации.
- <code>FEATURE_API=true</code>. Добавляет в интерфейс раздел **API** - удобный интерфейс для вычитки документации OpenAPI, оформленной в виде интерфейса Smartcat. Также поддерживает автоматические вычитку и перевод.
- <code>FEATURE_WATCH=true</code>. Добавляет в интерфейс раздел **Наблюдение** - используется для мониторинга изменений на указанных страницах. Use Case: разработчики изменили интерфейс сервиса, но не уведомили писателя.
- <code>FEATURE_SCREENSHOTS=true</code>. Добавляет в интерфейс раздел **Скриншоты** - мини версия Paint, используемая для быстрого закрашивания чувствительной информации на скриншотах.

<table>
  <tr>
    <td><img src="docs/screenshots/10-documents.png" alt="Репозиторий документов"></td>
    <td><img src="docs/screenshots/12-api.png" alt="Связка OpenAPI"></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/13-watch.png" alt="Наблюдение за страницами"></td>
    <td><img src="docs/screenshots/14-screenshots.png" alt="Редактор скриншотов"></td>
  </tr>
</table>

Как включить: [дополнительные разделы](https://badwisher.github.io/Peter-View/wiki/how-to/features/). Назначение: [документы](https://badwisher.github.io/Peter-View/wiki/how-to/documents/), [OpenAPI](https://badwisher.github.io/Peter-View/wiki/how-to/api/), [наблюдение](https://badwisher.github.io/Peter-View/wiki/how-to/watch/), [скриншоты](https://badwisher.github.io/Peter-View/wiki/how-to/screenshots/).

## Требования

- Установленный Docker Engine и плагин Docker Compose.
- Минимум 1.5 ГБ RAM для работы LanguageTool (Java).
- До 2 ГБ RAM для сервера приложений.
- Свободный порт на хосте (по умолчанию 3080, переменная PROOFREADER_PORT).

## Установка

```bash
git clone https://github.com/BadWisher/Peter-View.git
cd Peter-View
./deploy.sh
```

При отсутствии `.env` скрипт копирует `.env.example` и запускает три контейнера: интерфейс, сервер приложений, проверка языка. Первый запуск занимает около полутора минут. Когда в терминале появится «Готово», откройте http://localhost:3080.

Образы: `ghcr.io/badwisher/peter-view/backend` и `ghcr.io/badwisher/peter-view/frontend`. Данные хранятся в томе `backend-data`.

## Устройство

Система состоит из трёх Docker-контейнеров, объединённых в одну внутреннюю сеть. Для внешнего доступа с хоста открыт только один порт — PROOFREADER_PORT (по умолчанию 3080), который слушает nginx.

Когда пользователь открывает интерфейс в браузере, запрос сначала попадает в nginx, а затем перенаправляется к серверу приложения на базе FastAPI. Дальнейшая проверка текста устроена так: инструменты Vale и морфологический анализ работают прямо внутри этого контейнера приложения, а LanguageTool запущен отдельно. Подключение внешней языковой модели происходит опционально — только если администратор явно задал её адрес.

Все данные сохраняются в постоянном Docker-томе backend-data. Когда в интерфейсе раздела «Вычитка» запускается процесс проверки, он инициируется отправкой запроса POST /api/jobs.

Подробности: [архитектура](https://badwisher.github.io/Peter-View/wiki/explanation/architecture/), [как проходит проверка](https://badwisher.github.io/Peter-View/wiki/explanation/pipeline/), [хранилище](https://badwisher.github.io/Peter-View/wiki/reference/data/), [HTTP API](https://badwisher.github.io/Peter-View/wiki/reference/http/).

## Первый запуск

![Экран входа](docs/screenshots/01-login.png)

1. Войдите: логин `admin`, пароль `admin`.
2. Смените пароль. Меню учётной записи (инициалы слева внизу) → «Сменить пароль». Минимальная длина: 8 символов.
3. Откройте раздел «Вычитка».

![Форма проверки: источник и параметры](docs/screenshots/03-check-form.png)

4. Вкладка «Текст». Вставьте контрольный фрагмент из [установки и первого запуска](https://badwisher.github.io/Peter-View/wiki/tutorial/) и нажмите «Начать вычитку».
5. Дождитесь экрана «Очередь решений».
6. Удивитесь качеству вычитки и поставьте звезду репозиторию.

Полная последовательность с тем же фрагментом: [установка и первый запуск](https://badwisher.github.io/Peter-View/wiki/tutorial/).

Инструкции: [проверка источника](https://badwisher.github.io/Peter-View/wiki/how-to/check/), [список замечаний](https://badwisher.github.io/Peter-View/wiki/how-to/review/), [Style Guide](https://badwisher.github.io/Peter-View/wiki/how-to/styleguide/), [пользователи](https://badwisher.github.io/Peter-View/wiki/how-to/users/), [языковая модель](https://badwisher.github.io/Peter-View/wiki/how-to/llm/).

## Документация

| Задача | Раздел |
|---|---|
| Установка и контрольная проверка | [Установка и первый запуск](https://badwisher.github.io/Peter-View/wiki/tutorial/) |
| Файл, ссылка или другой текст | [Проверка источника](https://badwisher.github.io/Peter-View/wiki/how-to/check/) |
| Просмотр замечаний и таблица xlsx | [Список замечаний](https://badwisher.github.io/Peter-View/wiki/how-to/review/) |
| Пользователи и роли | [Пользователи](https://badwisher.github.io/Peter-View/wiki/how-to/users/) |
| Вход организации (Keycloak, Azure AD) | [OIDC](https://badwisher.github.io/Peter-View/wiki/how-to/oidc/) |
| Имена переменных | [Справка .env](https://badwisher.github.io/Peter-View/wiki/reference/config/) |
| Состав стека и путь запроса | [Архитектура](https://badwisher.github.io/Peter-View/wiki/explanation/architecture/) |
| Как из кнопки получается список | [Проверка](https://badwisher.github.io/Peter-View/wiki/explanation/pipeline/) |
| Файлы на томе | [Хранилище](https://badwisher.github.io/Peter-View/wiki/reference/data/) |
| HTTP API | [Справка API](https://badwisher.github.io/Peter-View/wiki/reference/http/) |
| Зачем система устроена так | [Назначение](https://badwisher.github.io/Peter-View/wiki/explanation/what/) |

Полный указатель: [документация](https://badwisher.github.io/Peter-View/wiki/).

## Лицензия

Проект распространяется под лицензией Apache-2.0.</br> 
Система не отправляет данные на адрес автора проекта. </br>
Проверка осуществляется локально или через указанные администратором внешние эндпоинты.

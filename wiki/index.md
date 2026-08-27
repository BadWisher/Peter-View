# Peter View

Проверка русской документации. Ставится у вас через Docker Compose.

В отчёт попадают Vale (правила Style Guide), pymorphy3 (морфология) и LanguageTool (грамматика). Проверка моделью выключена, пока администратор не укажет свой OpenAI-совместимый сервер.

## С чего начать

1. [Быстрый старт](quickstart.md): `./deploy.sh`, первый вход, первая проверка
2. [Установка и Docker](install.md): тома, память, прод, обновление
3. [Для ИТ](it.md): OIDC, SSRF, бэкап, cookie

Сайт проекта: [badwisher.github.io/Peter-View](https://badwisher.github.io/Peter-View/).

## Содержание

- [Что это такое](about.md)
- [Быстрый старт](quickstart.md)
- [Установка и Docker](install.md)
- [Конфигурация](config.md)
- [Роли и доступ](roles.md)
- [Для ИТ](it.md)
- [Разделы](sections.md)
- [Языковая модель и RAG](llm.md)
- [Скрытие разделов](features.md)
- [Архитектура](architecture.md)
- [Безопасность](security.md)
- [Разработка и тесты](develop.md)
- [FAQ](faq.md)

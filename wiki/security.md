# Безопасность

- Данные остаются в томе деплоя. Статистику сервис никуда не шлёт.
- Пароль не короче 8 символов. Сид `admin` / `admin` нужно сменить в первый день.
- Последнего администратора нельзя убрать.
- Cookie: HttpOnly, SameSite=lax, Secure по флагу.
- CSRF: Origin должен совпадать с Host на изменяющих запросах.
- Swagger выключен (`PROOFREADER_DOCS=false`).
- SSRF-фильтр на fetch URL. Для интранета `PROOFREADER_SSRF_ALLOW_PRIVATE=true`.
- Журнал: вход, пользователи, роли, настройки, запись Style Guide. Администратор читает его на экране системы.

Сообщить об уязвимости: [SECURITY.md](https://github.com/BadWisher/Peter-View/blob/main/SECURITY.md).

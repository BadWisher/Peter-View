# Безопасность

- Данные в томе деплоя. На сторону автора ничего не уходит. Модель вызывается только по адресу, который задал администратор.
- Пароль не короче 8 символов. Сид `admin` / `admin` смените в первый день.
- Последнего администратора нельзя убрать.
- Cookie: HttpOnly, SameSite=lax, Secure по `PROOFREADER_COOKIE_SECURE`.
- CSRF: на POST/PUT/PATCH/DELETE Origin должен совпадать с Host.
- Swagger выключен (`PROOFREADER_DOCS=false`).
- Fetch URL режется фильтром. Для интранета `PROOFREADER_SSRF_ALLOW_PRIVATE=true`, для публичного хоста `false`.
- Журнал: вход, пользователи, роли, настройки, запись Style Guide. Читается на экране «Система».
- Сессии сбрасываются при смене пароля. Есть лимит попыток входа по IP.

Сообщить об уязвимости: [SECURITY.md](https://github.com/BadWisher/Peter-View/blob/main/SECURITY.md). Публичный issue с эксплойтом не открывай.

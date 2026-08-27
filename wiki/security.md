# Безопасность

Сессия: cookie `proofreader_session`, HttpOnly, SameSite=lax, 12 часов. Живые сессии в памяти процесса: рестарт backend разлогинивает всех. Пароли: bcrypt, минимум 8 символов. После нескольких неверных попыток вход с IP закрывается на 5 минут.

Роли и OIDC: [роли](reference/roles.md).

Загрузка URL проходит проверку SSRF (`net_guard`): запрещены loopback, link-local, multicast. Адреса RFC1918 по умолчанию разрешены. На публичном хосте: `PROOFREADER_SSRF_ALLOW_PRIVATE=false`.

С хоста открыт только nginx. CSP на статике: скрипты `'self'`. Загрузки до 50 МБ.

Модель вызывается только по адресу, который задал администратор. На адрес репозитория проекта проверка ничего не отправляет.

Сообщить об уязвимости: [SECURITY.md](https://github.com/BadWisher/Peter-View/blob/main/SECURITY.md).

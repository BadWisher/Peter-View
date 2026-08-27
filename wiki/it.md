# Для ИТ

## Поток данных

Браузер ходит только на ваш хост (nginx на `PROOFREADER_PORT`). `/api` проксируется на FastAPI. LanguageTool доступен backend только из Docker-сети, с хоста его порта нет.

Модель и эмбеддинги вызываются, только если администратор задал URL. Сбора статистики нет, аккаунтов у автора проекта вы не создаёте.

## Ресурсы

LanguageTool: лимит 1.5 ГБ, `Java_Xmx=1g`, старт до ~90 секунд. Backend: лимит 2 ГБ. Диск: том `backend-data` плюс `./backups`.

## Бэкап

`make backup` кладёт tar в `./backups`. Восстановление: остановить стек, развернуть tar в данные тома, поднять снова. Образы сами по себе состояние не содержат.

## OIDC

Authorization code. Discovery: `OIDC_ISSUER/.well-known/openid-configuration`.

Redirect URI, один в один:

```
https://<хост>/api/auth/oidc/callback
```

**Keycloak.** Клиент confidential, standard flow, Valid redirect URIs как выше. Группы должны попасть в токен. Имена админских групп впиши в `OIDC_ADMIN_GROUPS` через запятую.

**Azure AD.** App registration, платформа Web, redirect URI тот же, client secret. Issuer:

```
https://login.microsoftonline.com/<tenant>/v2.0
```

Группы отдайте в ID token или userinfo.

SAML, LDAP и SCIM в 0.1 нет.

## SSRF

Вычитка умеет забирать страницу по URL. `PROOFREADER_SSRF_ALLOW_PRIVATE=true` пускает на RFC1918: удобно для внутренней wiki. Если тот же инстанс торчит в интернет, поставьте `false`.

## Cookie

За HTTPS: `PROOFREADER_COOKIE_SECURE=true`. Иначе браузер не сохранит сессию.

На изменяющих запросах Origin должен совпадать с Host (CSRF).

# Для ИТ

## Поток данных

Браузер ходит только на ваш хост. Backend вызывает LanguageTool в Docker-сети. Модель и эмбеддинги вызываются только по адресам, которые задал администратор. Сбора статистики нет.

## Ресурсы

LanguageTool любит ~1.5 ГБ RAM. Backend ограничьте 2 ГБ. Диск: том `backend-data` плюс `./backups`.

## Бэкап

`make backup` кладёт tar в `./backups`. Храните том отдельно от образов.

## OIDC

Authorization code. Discovery: `OIDC_ISSUER/.well-known/openid-configuration`.

Redirect URI: `https://<хост>/api/auth/oidc/callback`.

Пример клиента Keycloak: confidential, standard flow, valid redirect как выше, группы в токене. Впиши имена групп админов в `OIDC_ADMIN_GROUPS`.

Пример Azure AD: App Registration, Web redirect URI тот же, client secret, issuer `https://login.microsoftonline.com/<tenant>/v2.0`. Группы отдайте в ID token или userinfo.

SAML, LDAP и SCIM в этом выпуске нет.

## SSRF

`PROOFREADER_SSRF_ALLOW_PRIVATE=true` удобен для интранета: вычитка ходит на внутренние wiki и порталы. Если сервис торчит в интернет, поставьте `false`.

## Cookie

За HTTPS: `PROOFREADER_COOKIE_SECURE=true`.

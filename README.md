# Peter View

<img src="frontend/public/logo.png" width="72" height="72" alt="Peter View">

Проверка русской документации у себя. Vale, pymorphy3 и LanguageTool в одной очереди. Модель подключается отдельно, если она вам нужна.

[Сайт](https://badwisher.github.io/Peter-View/) · [Вики](https://badwisher.github.io/Peter-View/wiki/) · [Apache-2.0](LICENSE)

![Очередь решений](docs/screenshots/02-check.png)

## Поставить

Нужны Docker и Compose. Первый старт LanguageTool занимает около полутора минут.

```bash
git clone https://github.com/BadWisher/Peter-View.git
cd Peter-View
./deploy.sh
```

Открой http://localhost:3080. Логин `admin`, пароль `admin`. Пароль смени в тот же день.

Пошагово: [быстрый старт](wiki/quickstart.md).

## Что видно после входа

Вычитка, Style Guide, история, аналитика. Пользователей и настройки модели видит только администратор.

| Раздел | По умолчанию |
|---|---|
| Вычитка | включена |
| Style Guide | чтение у всех, правки у admin |
| История, аналитика | включены |
| Документы, OpenAPI, наблюдение, скриншоты | выключены, флаги `FEATURE_*` |

<p>
<img src="docs/screenshots/03-check-form.png" width="32%" alt="Форма проверки">
<img src="docs/screenshots/04-guides.png" width="32%" alt="Style Guide">
<img src="docs/screenshots/05-insights.png" width="32%" alt="Аналитика">
</p>

## Данные

Том Docker `backend-data`. На адрес автора проекта ничего не уходит. LanguageTool сидит в вашей сети. Модель вызывается только по URL, который задал администратор.

Роли, OIDC, память, бэкап: [для ИТ](wiki/it.md). Все переменные: [конфигурация](wiki/config.md).

Образы: `ghcr.io/badwisher/peter-view/backend` и `.../frontend`.

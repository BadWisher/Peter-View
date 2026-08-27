# Peter View

<img src="frontend/public/logo.png" width="72" height="72" alt="Peter View">

Проверка русской документации. Ставится через Docker Compose. Текст и отчёты лежат в томе на вашей машине.

В отчёт идут Vale, pymorphy3 и LanguageTool. Модель не вызывается, пока в настройках не пропишут URL.

![Проверка текста](docs/screenshots/02-check.png)

## Поставить

```bash
git clone https://github.com/BadWisher/Peter-View.git
cd Peter-View
./deploy.sh
```

Адрес: `http://localhost:3080`  
Логин `admin`, пароль `admin`. Пароль смени в тот же день.

## Разделы

Сразу доступны вычитка, Style Guide, история и аналитика. Пользователей и настройки модели видит только администратор.

Документы, OpenAPI, наблюдение и скриншоты выключены. В `.env`:

```env
FEATURE_DOCUMENTS=true
FEATURE_API=true
FEATURE_WATCH=true
FEATURE_SCREENSHOTS=true
```

Лицензия [Apache-2.0](LICENSE). Образы: `ghcr.io/badwisher/peter-view/backend` и `.../frontend`.

Роли, OIDC и остальные переменные: [вики](wiki/index.md).

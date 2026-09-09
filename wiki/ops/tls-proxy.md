# TLS и обратный прокси

Сам стек TLS не терминирует: nginx внутри контейнера слушает восьмой порт и печатает голые `http://`-адреса. HTTPS задача внешнего прокси на хосте, разделение сознательное: сертификат, ACME и HSTS живут у админа площадки, а не у приложения.

## Эталонная схема

```text
браузер --(443, TLS)--> внешний nginx/caddy на хосте --(127.0.0.1:3080)--> контейнер frontend
```

## Пример: nginx на хосте

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name peterview.example.ru;

    ssl_certificate     /etc/letsencrypt/live/peterview.example.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/peterview.example.ru/privkey.pem;

    client_max_body_size 60m;   # запас над 50m у внутреннего nginx

    location / {
        proxy_pass http://127.0.0.1:3080;
        proxy_http_version 1.1;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE: стрим прогресса проверки не должен буферизоваться
        proxy_buffering    off;
        proxy_read_timeout 900s;
    }
}

server {
    listen 80;
    server_name peterview.example.ru;
    return 301 https://$host$request_uri;
}
```

Ключевые детали:

- **`proxy_buffering off` обязателен.** Иначе стрим воркеров (`/api/jobs/*/stream`) превращается в «висит, потом всё сразу». Внутренний nginx буферизацию для стрима выключает, но внешний обязан сделать то же.
- **Тайм-ауты не короче 600 с** длинная LLM-проверка живёт до 900; внутренний nginx уже ждёт 600 на read/send.
- **`client_max_body_size`** выше 50 МБ uploads иначе DOCX на 50 МБ отсекается раньше, чем его заметит приложение (413 от вашего прокси).
- **`Host` и `X-Forwarded-*`** внутреннее приложение сверяет Origin/Referer с `Host` (CSRF-guard), кривой `Host` даёт ложные 403 «Перекрёстный запрос отклонён».

## Настройки приложения под HTTPS

После включения TLS обязательно:

1. `PROOFREADER_COOKIE_SECURE=true` в `.env` и перезапуск cookie сессии станет Secure, не будет утекать по http.
2. Если пользователи заходят с другого origin (например, домен-алиас), вычеркните его в `PROOFREADER_CORS_ORIGINS` через запятую. Same-origin deployments ничего не добавляют.

## Caddy-вариант (для ленивых)

```text
peterview.example.ru {
    reverse_proxy 127.0.0.1:3080
    flush_interval -1
}
```

Caddy сам получает сертификат Let's Encrypt и по умолчанию не буферизрует ответные стримы при `flush_interval -1`.

## Чего не делать

- Не выставляйте наружу backend:8000 и languagetool:8010. Стек спроектирован так, что единственный вход порт nginx-фронта; публикация backend ломает предпосылку CSRF-guard'а (приложение не знает о вашем прокси и сравнивает Host) и выкидывает LanguageTool в мир.
- Не включайте corp-proxy-мост (`172.17.0.1:3128`) на хосте с белым адресом: это открытый прокси в интернет.
- Не ставьте приложение на базовый порт 3080 с флагом `-p 80:80` «временно» без прокси: тогда и `X-Real-IP` нет, и CSRF-guard будет сверять Origin с голым хостом, и cookie улетает по http.

## Дальше

- [Усиление защиты](hardening.md) HSTS, брандмауэр, минимизация surface.
- [Переменные](config-env.md) `PROOFREADER_COOKIE_SECURE`.

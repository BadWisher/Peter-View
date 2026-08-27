#!/usr/bin/env bash
# Деплой Peter View одной командой: ./deploy.sh
# Идемпотентно — можно запускать повторно для обновления (пересоберёт изменившееся).
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PROOFREADER_PORT:-3080}"
if [ -f .env ] && grep -qE '^PROOFREADER_PORT=' .env 2>/dev/null; then
  PORT="$(grep -E '^PROOFREADER_PORT=' .env | tail -1 | cut -d= -f2- | tr -d ' \"'"'"'')"
fi

# Печатает адреса, по которым сервис доступен: и локально, и по корп-сети.
print_urls() {
  local suffix=":${PORT}"
  [ "$PORT" = "80" ] && suffix=""
  echo "Готово. Сервис доступен по адресам:"
  echo "  локально:   http://localhost${suffix}"
  # Все IPv4 хоста, кроме loopback и docker-мостов, — это и есть адреса в корп-сети.
  local ip
  for ip in $(hostname -I 2>/dev/null); do
    case "$ip" in
      *:*) continue ;;                                   # пропускаем IPv6
      127.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) continue ;;  # loopback и docker-мосты
    esac
    echo "  по сети:    http://${ip}${suffix}"
  done
  echo "  (если заведён DNS-хост — http://<имя>${suffix})"
}

# Выбираем доступную команду compose (v2 «docker compose» или старый «docker-compose»).
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "Не найден Docker Compose. Установи Docker с плагином compose." >&2
  exit 1
fi

# 1. .env: при отсутствии создаём из примера и предупреждаем про ключи.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан .env из .env.example."
  echo "  Впиши LLM_BASE_URL / LLM_API_KEY / EMBEDDING_* перед боевым запуском."
  echo "  Для прода за TLS поставь PROOFREADER_COOKIE_SECURE=true."
  echo "  На VDI с локальным корп-прокси: PROOFREADER_CORP_PROXY=true (см. вики)."
fi

COMPOSE_FILES=(-f docker-compose.yml)
if grep -qE '^PROOFREADER_CORP_PROXY=(1|true|yes|on|да|TRUE|YES|ON|Да)$' .env 2>/dev/null; then
  COMPOSE_FILES+=(-f docker-compose.corp-proxy.yml)
  _corp_upstream="127.0.0.1:3128"
  if grep -qE '^CORP_PROXY_UPSTREAM=' .env 2>/dev/null; then
    _corp_upstream="$(grep -E '^CORP_PROXY_UPSTREAM=' .env | tail -1 | cut -d= -f2- | tr -d ' \"'"'"'')"
  fi
  echo "Включён мост корп. HTTP-прокси (proxy-bridge → ${_corp_upstream})."
fi

# 2. Сборка и запуск всего стека.
if [[ " ${COMPOSE_FILES[*]} " == *" docker-compose.corp-proxy.yml "* ]]; then
  echo "Поднимаю proxy-bridge..."
  $COMPOSE "${COMPOSE_FILES[@]}" up -d proxy-bridge
fi
echo "Собираю и поднимаю контейнеры..."
$COMPOSE "${COMPOSE_FILES[@]}" up -d --build

# 3. Ждём, пока фронт начнёт отвечать (если есть curl).
if command -v curl >/dev/null 2>&1; then
  printf "Жду готовности"
  ready=""
  for _ in $(seq 1 30); do
    if curl -fsS --connect-timeout 2 --max-time 5 "http://localhost:${PORT}/" >/dev/null 2>&1; then ready=1; break; fi
    printf "."
    sleep 2
  done
  echo
  if [ -n "$ready" ]; then
    print_urls
    echo "Первый вход: admin / admin (сразу заведи своих в меню «Пользователи»)."
  else
    echo "Контейнеры подняты, но фронт ещё не ответил за 60 с."
    echo "Посмотри логи: $COMPOSE ${COMPOSE_FILES[*]} logs -f"
  fi
else
  print_urls
fi

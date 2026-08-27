#!/bin/sh
set -e

# Том data может уже принадлежать root (старые деплои) — чиним владельца, пока
# мы ещё root, затем сбрасываем привилегии и запускаем приложение под appuser.
mkdir -p /app/data
chown -R appuser:appuser /app/data 2>/dev/null || true

exec gosu appuser "$@"

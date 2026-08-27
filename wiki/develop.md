# Разработка и тесты

```bash
cp .env.example .env
pip install -r backend/requirements-dev.txt
make lint
make test
make config
```

Интерфейс без сборщика: правь файлы в `frontend/public/js/` и обнови `?v=` в `index.html` при жёстком кэше.

Вклад принимается под Apache-2.0, CLA нет. Подробности: [CONTRIBUTING.md](https://github.com/BadWisher/Peter-View/blob/main/CONTRIBUTING.md).

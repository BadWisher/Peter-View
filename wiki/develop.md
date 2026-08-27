# Разработка и тесты

Python 3.12.

```bash
cp .env.example .env
python3 -m pip install -r backend/requirements-dev.txt
make lint
make test
make config
```

Линт: ruff. Тесты: pytest. На хосте с Python 3.10 полный набор может не встать из-за numpy; тогда гоняйте `backend/tests/test_auth_roles.py` или тесты внутри образа.

Интерфейс без сборщика. Правишь `frontend/public/js/…` и обновляешь `?v=` у скриптов в `frontend/public/index.html`, если упёрлись в кэш.

Стек целиком: `./deploy.sh` или `make ci-local` (lint, test, config, сборка).

CLA нет. Отправляя PR, отдаёшь код под Apache-2.0. См. [CONTRIBUTING.md](https://github.com/BadWisher/Peter-View/blob/main/CONTRIBUTING.md).

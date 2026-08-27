.PHONY: deploy down logs ps update backup config lint test regression ci-local prod-config config-corp-proxy

COMPOSE_FILES := -f docker-compose.yml
ifeq ($(shell grep -qE '^PROOFREADER_CORP_PROXY=(1|true|yes|on|да|TRUE|YES|ON|Да)$$' .env 2>/dev/null && echo 1),1)
COMPOSE_FILES += -f docker-compose.corp-proxy.yml
endif

deploy:
	./deploy.sh

down:
	docker compose $(COMPOSE_FILES) down

logs:
	docker compose $(COMPOSE_FILES) logs -f

ps:
	docker compose $(COMPOSE_FILES) ps

update:
	git pull --ff-only
	./deploy.sh

backup:
	docker compose $(COMPOSE_FILES) exec backend sh -c 'tar czf /app/backups/manual-$$(date +%Y%m%d-%H%M%S).tgz -C /app/data .'
	@echo "Снимок сохранён в ./backups"

config:
	docker compose config --quiet

lint:
	python3 -m ruff check backend/app backend/eval backend/tests

test:
	python3 -m pytest -q

regression:
	docker compose $(COMPOSE_FILES) exec backend python -m app.regression_checks

ci-local: lint test config config-corp-proxy
	docker compose build

prod-config:
	@test -n "$(IMAGE_SHA)" || (echo "IMAGE_SHA is required" >&2; exit 2)
	@test -n "$(GHCR_REPOSITORY)" || (echo "GHCR_REPOSITORY is required" >&2; exit 2)
	IMAGE_SHA="$(IMAGE_SHA)" GHCR_REPOSITORY="$(GHCR_REPOSITORY)" \
		docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet

config-corp-proxy:
	docker compose -f docker-compose.yml -f docker-compose.corp-proxy.yml config --quiet

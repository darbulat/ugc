# Compose file sets (override in env if needed)
COMPOSE_TEST = docker compose -f docker-compose.test.yml
# Main + test: nginx from main compose (with test overlay) for e2e_telegram webhook
COMPOSE_TEST_WITH_MAIN = docker compose -f docker-compose.yml -f docker-compose.test.yml
COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

# Paths and coverage threshold (override for CI or different layout)
SRC_DIR ?= src
TEST_DIR ?= tests
COV_FAIL ?= 98
E2E_TIMEOUT ?= 90

# DB-changing targets must not run in parallel with make -j
.NOTPARALLEL: migrate restore-db restore-db-s3

.PHONY: help install-dev lint typecheck test coverage e2e e2e-dev e2e-docker e2e-telegram e2e-telegram-dev e2e-telegram-docker e2e-telegram-docker-auth e2e-telegram-clean test-docker test-all-docker test-all-dev test-all-docker-dev format format-check migrate docker-up docker-down deploy-apps-zero-downtime dev-up dev-down admin instagram-stats export-requirements backup-db restore-db restore-db-s3 list-backups list-backups-s3 base-backup list-base-backups-s3 upload-wal pitr-restore deploy-dev-e2e deploy-dev-e2e-watch all e2e-miniapp

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Development:  install-dev, format, format-check, lint, typecheck, test, coverage"
	@echo "E2E:          e2e, e2e-dev (Playwright vs dev), e2e-telegram-dev (Telegram vs dev; E2E_DATABASE_URL, E2E_CLEAN_TELEGRAM=darbulat), e2e-docker, e2e-telegram, e2e-telegram-docker, e2e-telegram-docker-auth, e2e-telegram-clean"
	@echo "Infra:        docker-up, docker-down, deploy-apps-zero-downtime, dev-up, dev-down, migrate, backup-db, restore-db, restore-db-s3, list-backups, list-backups-s3"
	@echo "PITR:         base-backup, list-base-backups-s3, upload-wal, pitr-restore TARGET_TIME=\"...\""
	@echo "Run:          admin, instagram-stats"
	@echo "Full check:   make all   (format + lint + typecheck + coverage)"
	@echo "Tests (Docker): test-docker, e2e-docker, test-all-docker (unit + integration + e2e in one run)"
	@echo "Tests (dev, in container, same network): test-all-docker-dev (DEV_NETWORK=ugc_default, E2E_* in .env)"
	@echo "Deploy+E2E:   deploy-dev-e2e BRANCH=<branch> (trigger GH workflow), deploy-dev-e2e-watch (watch latest run)"
	@echo "Export:       export-requirements"

export-requirements:
	uv export --no-dev --no-emit-project -o requirements.txt

install-dev:
	uv sync --all-extras

lint:
	uv run ruff check $(SRC_DIR) $(TEST_DIR)

format:
	uv run ruff format $(SRC_DIR) $(TEST_DIR)

format-check:
	uv run ruff format --check $(SRC_DIR) $(TEST_DIR)

typecheck:
	uv run mypy $(SRC_DIR)

test:
	uv run pytest -m "not e2e"

coverage:
	uv run pytest -m "not e2e" --cov=ugc_bot --cov-fail-under=$(COV_FAIL) --cov-report=term-missing --cov-report=xml

e2e:
	uv run python -m playwright install chromium
	uv run pytest $(TEST_DIR)/e2e -v -m e2e --timeout=$(E2E_TIMEOUT)

e2e-dev:
	@if [ -z "$${E2E_BASE_URL}" ]; then \
		echo "Error: E2E_BASE_URL is required. Example: E2E_BASE_URL=https://dev.usemycontent.ru make e2e-dev"; \
		exit 1; \
	fi
	uv run python -m playwright install chromium
	uv run pytest $(TEST_DIR)/e2e -v -m e2e --timeout=$(E2E_TIMEOUT)

e2e-telegram:
	uv sync --extra dev --extra telegram-e2e
	uv run pytest $(TEST_DIR)/e2e -m e2e_telegram -v --timeout=$(E2E_TIMEOUT)

# Starts app + nginx (from main compose with test overlay), then runs e2e_telegram. WEBHOOK_BASE_URL must point at nginx (e.g. ngrok to host:80). Requires in .env: TELEGRAM_E2E_BOT_TOKEN, WEBHOOK_BASE_URL, WEBHOOK_SECRET.
e2e-telegram-docker:
	$(COMPOSE_TEST_WITH_MAIN) build e2e-telegram
	$(COMPOSE_TEST_WITH_MAIN) run --rm e2e-telegram

# One-time auth: run with -it, enter code from Telegram; session saved in volume
e2e-telegram-docker-auth:
	$(COMPOSE_TEST_WITH_MAIN) build e2e-telegram
	$(COMPOSE_TEST_WITH_MAIN) run --rm -it e2e-telegram \
		python scripts/telegram_e2e_auth.py

# Clean E2E DB users (so each test run starts with no users). Requires E2E_DATABASE_URL.
e2e-telegram-clean:
	@if [ -z "$${E2E_DATABASE_URL}" ]; then \
		echo "Error: E2E_DATABASE_URL is required. Set to the same DB the bot uses for E2E."; \
		exit 1; \
	fi
	$(COMPOSE_TEST_WITH_MAIN) run --rm e2e-telegram \
		python scripts/clean_e2e_users.py

e2e-docker:
	$(COMPOSE_TEST) run --rm e2e

e2e-miniapp:  ## Mini App Playwright E2E tests (requires E2E_MINIAPP_URL, E2E_BOT_TOKEN)
	uv run pytest tests/e2e/test_miniapp_ui.py -v -m e2e

test-docker:
	$(COMPOSE_TEST) run --rm test

# One command: unit + integration + e2e + e2e_telegram. Uses nginx from main compose (test overlay); WEBHOOK_BASE_URL must point at nginx (e.g. ngrok to host:80). Requires TELEGRAM_E2E_BOT_TOKEN, WEBHOOK_BASE_URL, WEBHOOK_SECRET in .env.
test-all-docker:
	$(COMPOSE_TEST_WITH_MAIN) run --rm test-all

# Run full test suite in a container attached to the dev stack network (no Python on host). Set DEV_NETWORK to dev network name (e.g. ugc_default), E2E_BASE_URL=http://admin:8001, E2E_DATABASE_URL=postgresql+psycopg://...@db:5432/ugc, E2E_CLEAN_TELEGRAM=darbulat in .env.
test-all-docker-dev:
	@if [ -z "$${DEV_NETWORK}" ]; then \
		echo "Error: DEV_NETWORK is required (e.g. ugc_default). Get it: docker network ls | grep default"; \
		exit 1; \
	fi
	docker compose -f docker-compose.test-dev.yml build test-all-dev
	docker compose -f docker-compose.test-dev.yml run --rm test-all-dev

# One-time Telethon auth for test-all-docker-dev; session saved in volume. Run with -it: make test-all-docker-dev-auth
test-all-docker-dev-auth:
	docker compose -f docker-compose.test-dev.yml --profile auth run --rm -it test-all-dev-auth

# Sequential: backup DB (one-off), then run Alembic migrations in containers.
migrate:
	docker compose up --build -d db_backup
	docker compose up --build migrate

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

# Zero-downtime deploy for app and app_2: build once, then update one instance at a time
# so nginx always has at least one healthy backend. Optional: COMPOSE_ARGS="-f docker-compose.yml -f docker-compose.prod.yml"
deploy-apps:
	@./scripts/deploy_apps_zero_downtime.sh $(COMPOSE_ARGS)

# Dev contour: docker-compose.yml + docker-compose.dev.yml (no backup by default)
dev-up:
	$(COMPOSE_DEV) up -d --build

dev-down:
	$(COMPOSE_DEV) down

admin:
	uv run uvicorn ugc_bot.admin.app:app --host 0.0.0.0 --port 8001 --log-config config/uvicorn_log_config.json

# Database backup commands (DB params from DATABASE_URL or POSTGRES_* in .env)
backup-db:
	docker compose run --rm db_backup python scripts/backup_db.py --output-dir /backups

# BACKUP_FILE = path inside the db_backup container (e.g. /backups/ugc_backup_YYYYMMDD_HHMMSS.sql.gz from mounted volume)
restore-db:
	@if [ -z "$(BACKUP_FILE)" ]; then \
		echo "Error: BACKUP_FILE is required. Usage: make restore-db BACKUP_FILE=/backups/ugc_backup_YYYYMMDD_HHMMSS.sql.gz"; \
		exit 1; \
	fi
	docker compose run --rm db_backup python scripts/restore_db.py \
		--host db \
		--port 5432 \
		--database $${POSTGRES_DB:-ugc} \
		--user $${POSTGRES_USER:-ugc} \
		--password $${POSTGRES_PASSWORD:-ugc} \
		--confirm \
		$(BACKUP_FILE)

# Restore from S3. BACKUP_S3_KEY = object key in bucket, e.g. backups/ugc_backup_20240206_020000.sql.gz
# Path is resolved inside the db_backup container (S3 credentials from .env).
# Requires S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY (and optionally S3_ENDPOINT_URL, S3_BUCKET) in .env
restore-db-s3:
	@if [ -z "$(BACKUP_S3_KEY)" ]; then \
		echo "Error: BACKUP_S3_KEY is required. Usage: make restore-db-s3 BACKUP_S3_KEY=ugc_backup_YYYYMMDD_HHMMSS.sql.gz"; \
		echo "  Or list available backups: make list-backups-s3"; \
		exit 1; \
	fi
	docker compose run --rm db_backup python scripts/restore_db.py \
		--host db \
		--port 5432 \
		--database $${POSTGRES_DB:-ugc} \
		--user $${POSTGRES_USER:-ugc} \
		--password $${POSTGRES_PASSWORD:-ugc} \
		--from-s3 \
		--confirm \
		$(BACKUP_S3_KEY)

# List backup objects in S3 (requires S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY in .env)
list-backups-s3:
	docker compose run --rm db_backup python scripts/restore_db.py --list-s3

list-backups:
	docker compose run --rm db_backup ls -lh /backups/

# PITR: create base backup (pg_basebackup) for point-in-time recovery
base-backup:
	docker compose run --rm db_backup python scripts/base_backup.py --output-dir /backups/base

# PITR: list base backups in S3
list-base-backups-s3:
	docker compose run --rm db_backup python scripts/pitr_restore.py --list

# PITR: upload pending WAL files to S3
upload-wal:
	docker compose run --rm db_backup python scripts/wal_uploader.py

# PITR: full restore — stops all services, restores from S3, restarts everything.
# Usage: make pitr-restore                                  (restore to latest)
#        make pitr-restore TARGET_TIME="2026-03-13 10:00:00"
pitr-restore:
	@bash scripts/pitr_restore_docker.sh $(if $(TARGET_TIME),--target-time "$(TARGET_TIME)")

# Deploy branch to dev and run E2E via GitHub Actions workflow.
# Usage: make deploy-dev-e2e BRANCH=my-feature  (or omit BRANCH to use current branch)
deploy-dev-e2e:
	$(eval BRANCH ?= $(shell git branch --show-current))
	gh workflow run deploy-dev-e2e.yml --ref $(BRANCH) -f branch=$(BRANCH)
	@echo "Workflow triggered for branch: $(BRANCH)"
	@echo "Watch with: make deploy-dev-e2e-watch"

# Watch the latest deploy-dev-e2e workflow run
deploy-dev-e2e-watch:
	@RUN_ID=$$(gh run list --workflow=deploy-dev-e2e.yml --limit=1 --json databaseId -q '.[0].databaseId'); \
	if [ -z "$$RUN_ID" ]; then \
		echo "No runs found for deploy-dev-e2e.yml"; \
		exit 1; \
	fi; \
	echo "Watching run $$RUN_ID..."; \
	gh run watch "$$RUN_ID"

# Full CI check (matches GitHub Actions): no auto-format, just verify. Use 'make fix' to auto-format first.
all: format-check lint typecheck coverage

# Auto-format then run full CI check
fix: format all

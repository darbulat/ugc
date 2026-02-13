.PHONY: install-dev lint typecheck test coverage e2e e2e-dev e2e-docker e2e-telegram e2e-telegram-docker e2e-telegram-docker-auth test-docker test-all-docker format migrate docker-up docker-down admin subscribe-instagram-webhook list-instagram-subscriptions export-requirements backup-db restore-db restore-db-s3 list-backups list-backups-s3

export-requirements:
	uv export --no-dev --no-emit-project -o requirements.txt

install-dev:
	uv run pip install -e ".[dev]"

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

format-check:
	uv run ruff format --check src tests

typecheck:
	uv run mypy src

test:
	uv run pytest -m "not e2e"

coverage:
	uv run pytest -m "not e2e" --cov=ugc_bot --cov-fail-under=98 --cov-report=term-missing --cov-report=xml

e2e:
	uv run python -m playwright install chromium
	uv run pytest tests/e2e -v -m e2e --timeout=90

e2e-dev:
	@if [ -z "$${E2E_BASE_URL}" ]; then \
		echo "Error: E2E_BASE_URL is required. Example: E2E_BASE_URL=https://dev.usemycontent.ru make e2e-dev"; \
		exit 1; \
	fi
	uv run python -m playwright install chromium
	uv run pytest tests/e2e -v -m e2e --timeout=90

e2e-telegram:
	uv sync --extra dev --extra telegram-e2e
	uv run pytest tests/e2e -m e2e_telegram -v --timeout=90

e2e-telegram-docker:
	docker compose -f docker-compose.test.yml build e2e-telegram
	docker compose -f docker-compose.test.yml run --rm e2e-telegram

# One-time auth: run with -it, enter code from Telegram; session saved in volume
e2e-telegram-docker-auth:
	docker compose -f docker-compose.test.yml build e2e-telegram
	docker compose -f docker-compose.test.yml run --rm -it e2e-telegram \
		python scripts/telegram_e2e_auth.py

# Clean E2E DB users (so each test run starts with no users). Requires E2E_DATABASE_URL.
e2e-telegram-clean:
	@if [ -z "$${E2E_DATABASE_URL}" ]; then \
		echo "Error: E2E_DATABASE_URL is required. Set to the same DB the bot uses for E2E."; \
		exit 1; \
	fi
	docker compose -f docker-compose.test.yml run --rm e2e-telegram \
		python scripts/clean_e2e_users.py

e2e-docker:
	docker compose -f docker-compose.test.yml run --rm e2e

test-docker:
	docker compose -f docker-compose.test.yml run --rm test

test-all-docker: test-docker e2e-docker

migrate:
	alembic upgrade head

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

admin:
	uvicorn ugc_bot.admin.app:app --host 0.0.0.0 --port 8001 --log-config config/uvicorn_log_config.json

# Database backup commands (DB params from DATABASE_URL or POSTGRES_* in .env)
backup-db:
	docker compose run --rm db_backup python scripts/backup_db.py --output-dir /backups

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

# Restore from S3. BACKUP_S3_KEY = object key, e.g. backups/ugc_backup_20240206_020000.sql.gz or ugc_backup_20240206_020000.sql.gz
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

all: format lint typecheck coverage

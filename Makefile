.PHONY: install-dev lint typecheck test coverage e2e e2e-docker test-docker test-all-docker format migrate docker-up docker-down admin subscribe-instagram-webhook list-instagram-subscriptions export-requirements backup-db restore-db list-backups

export-requirements:
	uv export --no-dev --no-emit-project -o requirements.txt

install-dev:
	uv run pip install -e ".[dev]"

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

typecheck:
	uv run mypy src

test:
	uv run pytest -m "not e2e"

coverage:
	uv run pytest -m "not e2e" --cov=ugc_bot --cov-report=term-missing --cov-report=xml

e2e:
	uv run python -m playwright install chromium
	uv run pytest tests/e2e -v -m e2e --timeout=90

e2e-telegram:
	uv sync --extra dev --extra telegram-e2e
	uv run pytest tests/e2e -m e2e_telegram -v --timeout=90

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

# Database backup commands
backup-db:
	docker compose run --rm db_backup python scripts/backup_db.py \
		--host db \
		--port 5432 \
		--database $${POSTGRES_DB:-ugc} \
		--user $${POSTGRES_USER:-ugc} \
		--password $${POSTGRES_PASSWORD:-ugc} \
		--output-dir /backups

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

list-backups:
	docker compose run --rm db_backup ls -lh /backups/

all: format lint typecheck coverage

.PHONY: install-dev lint typecheck test coverage format migrate docker-up docker-down admin subscribe-instagram-webhook list-instagram-subscriptions export-requirements

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
	uv run pytest

coverage:
	uv run pytest --cov=ugc_bot --cov-report=term-missing --cov-fail-under=97

migrate:
	alembic upgrade head

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

admin:
	uvicorn ugc_bot.admin.app:app --host 0.0.0.0 --port 8001 --log-config config/uvicorn_log_config.json

# Instagram Webhook commands
# These commands run inside the Docker container where Python and dependencies are available
subscribe-instagram-webhook:
	docker compose run --rm instagram_webhook python scripts/subscribe_instagram_webhook.py

subscribe-instagram-webhook-page:
	@if [ -z "$(PAGE_ID)" ]; then \
		echo "Error: PAGE_ID is required. Usage: make subscribe-instagram-webhook-page PAGE_ID=your_page_id"; \
		exit 1; \
	fi
	docker compose run --rm instagram_webhook python scripts/subscribe_instagram_webhook.py --page-id $(PAGE_ID)

list-instagram-subscriptions:
	docker compose run --rm instagram_webhook python scripts/subscribe_instagram_webhook.py --list

all: format lint typecheck coverage

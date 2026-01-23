.PHONY: install-dev lint typecheck test coverage format migrate docker-up docker-down admin subscribe-instagram-webhook list-instagram-subscriptions

install-dev:
	python3 -m pip install -e ".[dev]"

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

typecheck:
	uv run mypy src

test:
	uv run pytest

coverage:
	uv run pytest --cov=ugc_bot --cov-report=term-missing --cov-fail-under=90

migrate:
	alembic upgrade head

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

admin:
	uvicorn ugc_bot.admin.app:app --host 0.0.0.0 --port 8001

# Instagram Webhook commands
subscribe-instagram-webhook:
	uv run python scripts/subscribe_instagram_webhook.py

subscribe-instagram-webhook-page:
	@if [ -z "$(PAGE_ID)" ]; then \
		echo "Error: PAGE_ID is required. Usage: make subscribe-instagram-webhook-page PAGE_ID=your_page_id"; \
		exit 1; \
	fi
	uv run python scripts/subscribe_instagram_webhook.py --page-id $(PAGE_ID)

list-instagram-subscriptions:
	uv run python scripts/subscribe_instagram_webhook.py --list

all: format lint typecheck coverage
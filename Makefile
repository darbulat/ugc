.PHONY: install-dev lint typecheck test coverage format migrate docker-up docker-down admin

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

all: format lint typecheck coverage
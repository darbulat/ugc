#.PHONY: install-dev lint typecheck test coverage format migrate docker-up docker-down

install-dev:
	python3 -m pip install -e ".[dev]"

lint:
	ruff check src tests

format:
	ruff format src tests

typecheck:
	mypy src

test:
	pytest

coverage:
	pytest --cov=ugc_bot --cov-report=term-missing --cov-fail-under=90

migrate:
	alembic upgrade head

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

all: format lint typecheck coverage
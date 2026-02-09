FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install PostgreSQL client tools for backups
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client gzip && \
    rm -rf /var/lib/apt/lists/*

# 1. Слой зависимостей — кэшируется при изменении только кода
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# 2. Код приложения — при правках пересобирается только этот слой
COPY pyproject.toml alembic.ini /app/
COPY src /app/src
COPY config /app/config
COPY scripts /app/scripts
RUN pip install --no-cache-dir -e . --no-deps

CMD ["python", "-m", "ugc_bot.app"]

# E2E test target: dev deps + Playwright
FROM python:3.13-slim AS e2e

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client gzip && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml /app/
COPY src /app/src
COPY config /app/config
COPY scripts /app/scripts
COPY alembic.ini /app/
COPY tests /app/tests

RUN pip install --no-cache-dir --upgrade pip && \
    pip install -r requirements.txt && \
    pip install -e ".[dev]" && \
    pip install pytest pytest-cov pytest-asyncio pytest-timeout

RUN python -m playwright install --with-deps chromium

WORKDIR /app

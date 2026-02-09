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

FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install PostgreSQL 16 client for backups (match postgres:16-alpine server version;
# distro's postgresql-client can be PG17 and emit SET transaction_timeout, breaking restore on PG16)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gzip && \
    install -d /usr/share/keyrings && \
    curl -sSL -o /usr/share/keyrings/pgdg.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc && \
    (. /etc/os-release && echo "deb [signed-by=/usr/share/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list) && \
    apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client-16 && \
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

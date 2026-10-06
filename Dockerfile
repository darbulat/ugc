FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

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

# MAX API's current TLS chain is issued by the Russian Trusted Root CA.
# Trust the official root for MAX API's platform-api2.max.ru endpoint.
COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian-trusted-root-ca.crt
RUN echo 'aa800ef345422d6158c6fafe1c06c429dbda21c3df4bb1ccb45a920ec1111399  /usr/local/share/ca-certificates/russian-trusted-root-ca.crt' | sha256sum -c - && \
    update-ca-certificates

# 1. Слой зависимостей — кэшируется при изменении только кода
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

# 2. Код приложения — при правках пересобирается только этот слой
COPY pyproject.toml alembic.ini /app/
COPY src /app/src
COPY config /app/config
COPY scripts /app/scripts

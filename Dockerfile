FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Install PostgreSQL 16 client for backups (match postgres:16-alpine server version;
# distro's postgresql-client can be PG17 and emit SET transaction_timeout, breaking restore on PG16)
# PostgreSQL Debian Repository key: B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8.
COPY certs/postgresql-apt.asc /usr/share/keyrings/pgdg.asc
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl gzip && \
    (. /etc/os-release && echo "deb [signed-by=/usr/share/keyrings/pgdg.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list) && \
    apt-get update -o Acquire::Retries=3 -o APT::Update::Error-Mode=any && \
    apt-get install -y --no-install-recommends -o Acquire::Retries=3 postgresql-client-16 && \
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
RUN rm -f /app/scripts/clean_e2e_users.py \
    /app/scripts/telegram_e2e_auth.py \
    /app/scripts/run_local_tests.sh \
    /app/scripts/run_umc_synthetic_e2e.sh

# Named volume shared by both Telegram replicas, MAX and cleanup/delivery.
ENV ORDER_IMAGE_DIRECTORY=/app/var/order-images
RUN install -d -m 0700 /app/var/order-images

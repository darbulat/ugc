FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml /app/
COPY alembic.ini /app/
COPY src /app/src
COPY config /app/config
RUN pip install --upgrade pip && pip install -e .

CMD ["python", "-m", "ugc_bot.app"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY packages/krtour-map-admin ./packages/krtour-map-admin
COPY docker/api-entrypoint.sh ./docker/api-entrypoint.sh

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e . -e packages/krtour-map-admin \
    && chmod +x ./docker/api-entrypoint.sh

EXPOSE 9011

CMD ["./docker/api-entrypoint.sh"]

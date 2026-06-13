FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src
COPY packages/kor-travel-map-api ./packages/kor-travel-map-api

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --prefix=/install . ./packages/kor-travel-map-api

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

COPY --from=builder /install /usr/local
COPY alembic.ini ./
COPY alembic ./alembic
COPY docker/api-entrypoint.sh ./docker/api-entrypoint.sh

RUN chmod +x ./docker/api-entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 12301

CMD ["./docker/api-entrypoint.sh"]

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

# ADR-066 T-VN-01 — API image는 production 배포 아티팩트다. compose 밖에서 바로
# 실행해도 fail-closed 기동 검증이 걸리도록 image 기본 profile을 production으로 둔다.
ARG KOR_TRAVEL_MAP_GIT_COMMIT=development

LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KOR_TRAVEL_MAP_IMAGE_REVISION="$KOR_TRAVEL_MAP_GIT_COMMIT" \
    KOR_TRAVEL_MAP_API_PROFILE=production

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
COPY --chown=appuser:appuser docker/application-schema-head.py /usr/local/bin/ktm-application-schema
COPY --chown=appuser:appuser scripts/h35/h35_cutover.py ./scripts/h35/h35_cutover.py
COPY --chown=appuser:appuser resources/curations ./resources/curations

RUN chmod 0755 /usr/local/bin/ktm-application-schema \
    && chmod +x ./docker/api-entrypoint.sh ./scripts/h35/h35_cutover.py \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 12701

CMD ["./docker/api-entrypoint.sh"]
